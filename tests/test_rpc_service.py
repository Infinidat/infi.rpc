import gevent
from unittest import TestCase
from infi.rpc import (Client, Server, ServiceWithSynchronized,
                      ZeroRPCClientTransport, ZeroRPCServerTransport,
                      rpc_call, synchronized)
from infi.pyutils.contexts import contextmanager
from logbook import Logger

logger = Logger('test')


class SynchService(ServiceWithSynchronized):
    @rpc_call
    @synchronized
    def sync_call(self):
        gevent.sleep(1)
        return 1


@contextmanager
def server_context(service, **kwargs):
    server_transport = ZeroRPCServerTransport.create_tcp(8192)
    server = Server(transport=server_transport, service=service, **kwargs)
    server.bind()
    try:
        yield server
    finally:
        if server:
            server.unbind()


def create_client():
    return Client(ZeroRPCClientTransport.create_tcp(8192))


class ServerRPCTestCase(TestCase):
    def test_sync_call(self):
        with server_context(SynchService(), max_response_time=0.1):
            client_1 = create_client()
            client_2 = create_client()
            result_1 = client_1.sync_call(async_rpc=True)
            result_2 = client_2.sync_call(async_rpc=True)
            self.assertFalse(result_1.is_done())
            self.assertFalse(result_2.is_done())
            self.assertEqual(1, result_1.get_result())
            self.assertEqual(1, result_2.get_result())
