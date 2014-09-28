from unittest import TestCase
from infi.rpc.errors import TimeoutExpired
from infi.rpc.base.protocol import RPC_RESULT_CODE_ERROR
from infi.rpc.zerorpc.client import ZeroRPCClientTransport
from infi.rpc.zerorpc.server import ZeroRPCServerTransport
from infi.pyutils.contexts import contextmanager

PORT = 9898


def method_not_found_error(name):
    return dict(code=RPC_RESULT_CODE_ERROR)


@contextmanager
def server_bind_context(callback, *args, **kwargs):
    server = ZeroRPCServerTransport.create_tcp(PORT, *args, **kwargs)
    try:
        server.bind(callback)
        yield server
    finally:
        server.unbind()


@contextmanager
def client_connect_context(*args, **kwargs):
    client = ZeroRPCClientTransport.create_tcp(PORT, *args, **kwargs)
    client.connect()
    try:
        yield client
    finally:
        client.close()


class ZeroRPCTransportTestCase(TestCase):
    def test_simple_method(self):
        def foo(_):
            return 42

        with server_bind_context(foo):
            with client_connect_context() as client:
                self.assertEquals(42, client.call(1))
                self.assertEquals(42, client.call(2))

    def test_client_timeout_expired(self):
        client = ZeroRPCClientTransport.create_tcp(PORT, timeout=0.1)
        try:
            client.connect()  # zerorpc's connect doesn't really raise TimeoutExpired
        except TimeoutExpired:
            self.fail("connect() raised TimeoutExpired")
        self.assertRaises(TimeoutExpired, client.call, None)

    def test_client_invalid_rpc_method(self):
        def callback(_):
            return 42
        with server_bind_context(callback):
            import zerorpc
            client = zerorpc.Client("tcp://localhost:9898")
            result = client.unknown_func(1)
            self.assertEquals(result['code'], RPC_RESULT_CODE_ERROR)
