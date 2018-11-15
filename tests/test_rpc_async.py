import gevent
from unittest import TestCase
from infi.rpc import Client, AsyncServer, ServiceBase, ZeroRPCClientTransport, ZeroRPCServerTransport, rpc_call
from infi.logging.plugins.request_id_tag import get_tag
from infi.pyutils.contexts import contextmanager
from logbook import Logger

logger = Logger('test')


class FooService(ServiceBase):
    @rpc_call
    def foo(self):
        logger.debug('foo called with request id tag {}'.format(get_tag()))
        gevent.sleep(1)
        logger.debug('foo returning')
        return 42

    @rpc_call
    def bar(self):
        return 24


@contextmanager
def async_server_context(service, **kwargs):
    server_transport = ZeroRPCServerTransport.create_tcp(8192)
    server = AsyncServer(transport=server_transport, service=service, **kwargs)
    server.bind()
    try:
        yield server
    finally:
        if server:
            server.unbind()


class AsyncRPCTestCase(TestCase):
    def test_straightforward(self):
        with async_server_context(FooService()) as server:
            client_transport = ZeroRPCClientTransport.create_tcp(8192)
            client = Client(client_transport)
            self.assertEqual(client.foo(), 42)
            self.assertFalse(server.has_deferred_requests())

    def test_abandon_deferred_requests(self):
        with async_server_context(FooService(), interval_to_keep_result=0.1) as server:
            client_transport = ZeroRPCClientTransport.create_tcp(8192)
            client = Client(client_transport)
            client.bar(async_rpc=True)
            self.assertTrue(server.has_deferred_requests())
            gevent.sleep(0.2)
            server.garbage_collect_deferred_results()
            self.assertFalse(server.has_deferred_requests())

    def test_wait_for_deferred_requests__finish(self):
        with async_server_context(FooService(), interval_to_keep_result=5) as server:
            client_transport = ZeroRPCClientTransport.create_tcp(8192)
            client = Client(client_transport)
            deferred = client.bar(async_rpc=True)
            self.assertTrue(server.has_deferred_requests())
            g = gevent.spawn(deferred.get_result)
            server.wait_for_empty_deferred_requests()
            self.assertEqual(24, g.get())
            server.garbage_collect_deferred_results()
            self.assertFalse(server.has_deferred_requests())

    def test_wait_for_deferred_requests__abort(self):
        with async_server_context(FooService(), interval_to_keep_result=5) as server:
            client_transport = ZeroRPCClientTransport.create_tcp(8192)
            client = Client(client_transport)
            client.bar(async_rpc=True)
            self.assertTrue(server.has_deferred_requests())
            self.assertFalse(server.wait_for_empty_deferred_requests(0.1))
            server.garbage_collect_deferred_results()

    def test_wait_for_deferred_requests__abandon(self):
        with async_server_context(FooService(), interval_to_keep_result=0.1,
                                  result_garbage_collector_interval=0.1) as server:
            client_transport = ZeroRPCClientTransport.create_tcp(8192)
            client = Client(client_transport)
            client.bar(async_rpc=True)
            self.assertTrue(server.has_deferred_requests())
            self.assertTrue(server.wait_for_empty_deferred_requests(0.4))
