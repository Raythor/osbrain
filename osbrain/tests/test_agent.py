import time
import pytest
import random
from threading import Timer
from osbrain.logging import run_logger
from osbrain.core import locate_ns
from osbrain.core import run_agent
from osbrain.core import BaseAgent
from osbrain.core import Agent
from osbrain.core import Proxy
from osbrain.core import NSProxy
from osbrain.core import NameServer
from osbrain.core import SocketAddress

from common import nsaddr


def test_nameserver(nsaddr):
    """
    A simple test that checks the correct creation of a name server.
    """
    nsproxy = NSProxy(nsaddr)
    agents = nsproxy.list()
    name = 'Pyro.NameServer'
    assert len(agents) == 1
    assert list(agents.keys())[0] == name
    assert agents[name] == 'PYRO:%s@%s' % (name, nsaddr)


def test_locate_ns():
    """
    Locate nameserver as fast as possible. The function `locate_ns` should
    have a timeout before raising an error.
    """
    while True:
        try:
            # Bind to random port
            host = '127.0.0.1'
            port = random.randrange(10000, 20000)
            addr = SocketAddress(host, port)
            ns = NameServer(addr)
            # Start name server later
            Timer(1, ns.start).start()
            # Locate name server now
            nsaddr = NSProxy(addr).addr()
        except PermissionError:
            continue
        break
    assert nsaddr.host == host
    assert nsaddr.port == port
    ns.shutdown()


def test_early_agent_proxy(nsaddr):
    """
    It must be possible to create a Proxy when the registration of the new
    agent is imminent, even if it has not occured yet. A timeout will occur
    in case the agent could not be located.
    """
    agent = Agent('a0', nsaddr)
    # Start agent later
    Timer(1, agent.start).start()
    # Locate agent now
    a0 = Proxy('a0', nsaddr)
    assert a0.test() == 'OK'
    a0.kill()


def test_agent_loopback(nsaddr):
    """
    An agent should always have a loopback inproc socket.
    """
    a0 = run_agent('a0', nsaddr)
    assert a0.get_addr('loopback') == 'inproc://loopback'


def test_ping(nsaddr):
    """
    Test simple loopback ping.
    """
    a0 = run_agent('a0', nsaddr)
    assert a0.ping() == 'PONG'


def test_registration(nsaddr):
    """
    Verify new agents get registered in the nameserver.
    """
    a0 = run_agent('a0', nsaddr)
    a1 = run_agent('a1', nsaddr)
    # List registered agents
    agent_list = NSProxy(nsaddr).list()
    assert 'a0' in agent_list
    assert 'a1' in agent_list


def test_agent_shutdown(nsaddr):
    """
    An agent must unregister itself before shutting down.
    """
    agent = Agent('a0', nsaddr)
    agent.start()
    a0 = Proxy('a0', nsaddr)
    a0.run()
    ns = NSProxy(nsaddr)
    assert 'a0' in ns.list()
    a0.shutdown()
    agent.join()
    assert 'a0' not in ns.list()


def test_socket_creation(nsaddr):
    """
    Test ZMQ socket creation.
    """
    a0 = run_agent('a0', nsaddr)
    a0.bind('REQ', 'alias0')
    a0.bind('PUB', 'alias1')
    a0.bind('PUSH', 'alias2')
    addresses = a0.get_attr('address')
    assert 'alias0' in addresses
    assert 'alias1' in addresses
    assert 'alias2' in addresses


# TODO: this functions are used just within the scope of the next test.
#       Could we directly send the bytecode to the agent so that we can
#       declare them within a more constrained scope? (i.e. in the test code).
def rep_handler(agent, message):
    return 'OK'
def redirect(agent, message):
    agent.send('push', '%s (redirected)' % message)
def set_received(agent, message, topic=None):
    agent.received = message


def test_reqrep(nsaddr):
    """
    Simple request-reply pattern between two agents.
    """
    a0 = run_agent('a0', nsaddr)
    a1 = run_agent('a1', nsaddr)
    addr = a0.bind('REP', 'reply', rep_handler)
    a1.connect(addr, 'request')
    response = a1.send_recv('request', 'Hello world')
    assert response == 'OK'


def test_pushpull(nsaddr):
    """
    Simple push-pull pattern test.
    """
    a0 = run_agent('a0', nsaddr)
    a1 = run_agent('a1', nsaddr)
    addr = a1.bind('PULL', handler=redirect)
    a0.connect(addr, 'push')
    # Create a BaseAgent as end-point
    a2 = BaseAgent('a2')
    a2.received = ''
    addr = a2.bind('PULL', handler=set_received)
    a1.connect(addr, 'push')
    # Send message (will be passed from a0 to a1 and then to a2)
    message = 'Hello world'
    a0.send('push', message)
    while not a2.received:
        a2.iterate()
    assert a2.received == '%s (redirected)' % message


def test_pubsub(nsaddr):
    """
    Simple publisher-subscriber pattern test.
    """
    a0 = run_agent('a0', nsaddr)
    a1 = run_agent('a1', nsaddr)
    addr = a1.bind('SUB', handler=redirect)
    a0.connect(addr, 'pub')
    # Create a BaseAgent as end-point
    a2 = BaseAgent('a2')
    a2.received = ''
    a2.poll_timeout = 200
    addr = a2.bind('PULL', handler=set_received)
    a1.connect(addr, 'push')
    # Send message (will be passed from a0 to a1 and then to a2)
    while not a2.received:
        message = 'Hello world'
        a0.send('pub', message)
        a2.iterate()
    assert a2.received == '%s (redirected)' % message


def test_agent_inheritance(nsaddr):
    """
    Test agent inheritance; agents can be based on a custom class.
    """
    class NewAgent(BaseAgent):
        def the_answer_to_life(self):
            return 42

    # Test an Agent based on the new class
    Agent('new', nsaddr=nsaddr, base=NewAgent).start()
    new = Proxy('new', nsaddr)
    assert new.the_answer_to_life() == 42

    # Test the quick `run_agent` function
    a0 = run_agent('a0', nsaddr, base=NewAgent)
    assert a0.the_answer_to_life() == 42


def test_logger(nsaddr):
    """
    TODO
    """
    logger = run_logger('logger', nsaddr)
    a0 = run_agent('a0', nsaddr)
    # TODO: automatically connect to logger if it is already registered in
    #       the name server
    addr = logger.get_addr('logger_sub_socket')
    a0.connect(addr, 'log')
    message = 'Hello world'
    while True:
        a0.log_info(message)
        history = logger.get_attr('log_history')
        if len(history):
            break
    assert message in history[0]


def test_method_handlers(nsaddr):
    """
    Test handlers which are methods of a custom class.
    """
    class NewAgent(BaseAgent):
        def rep(self, message):
            self.received['rep'] = message
            self.connect(message, 'endpoint')
            return 'OK'
        def pull(self, message):
            self.received['pull'] = message
            self.send('endpoint', message + ' (redirected)')
        def on_init(self):
            self.received = {}
            self.bind('REP', 'rep', handler=self.rep)
            self.bind('PULL', 'pull', handler=self.pull)

    server = run_agent('server', nsaddr, base=NewAgent)
    client = run_agent('client', nsaddr)
    # Create a BaseAgent as end-point
    endpoint = BaseAgent('endpoint')
    endpoint.received = ''
    endpoint_addr = endpoint.bind('PULL', handler=set_received)
    # Request
    client.connect(server.get_addr('rep'), 'req')
    assert client.send_recv('req', endpoint_addr) == 'OK'
    assert server.get_attr('received')['rep'] == endpoint_addr
    # Push
    client.connect(server.get_addr('pull'), 'push')
    client.send('push', 'Hello')
    while not endpoint.received:
        endpoint.iterate()
    assert server.get_attr('received')['pull'] == 'Hello'
    assert endpoint.received == 'Hello (redirected)'


# TODO:
#  - Test handler with 2 parameters (agent, message)
#  - Test handler with 3 parameters (agent, message, topic)
#  - Test topic is properly filtered (no match, partial match, full match)