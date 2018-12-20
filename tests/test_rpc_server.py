from __future__ import print_function
import gevent
import logbook
from unittest import TestCase
from infi.rpc import (Client, AutoTimeoutClient, Server, ServiceBase, ZeroRPCClientTransport, ZeroRPCServerTransport,
                      rpc_call, rpc_deferred)
from infi.rpc.errors import TimeoutExpired
from infi.pyutils.contexts import contextmanager
from logbook import Logger

logger = Logger('test')


class FooService(ServiceBase):
    @rpc_call
    def no_delay_call(self):
        return 1

    @rpc_call
    def delay_call(self):
        gevent.sleep(1)
        return 2

    @rpc_deferred
    def no_delay_deferred_call(self):
        return 3

    @rpc_deferred
    def delay_deferred_call(self):
        gevent.sleep(1)
        return 4

    @rpc_call
    def stuck_call(self):
        from time import sleep
        sleep(1)
        return 5


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
    def test_no_delay_call(self):
        with server_context(FooService(), max_response_time=1):
            client = create_client()
            result = client.no_delay_call(async_rpc=True)
            self.assertTrue(result.is_done())
            self.assertEqual(1, result.get_result())

    def test_delay_call__above_max_response_time(self):
        with server_context(FooService(), max_response_time=0.5):
            client = create_client()
            result = client.delay_call(async_rpc=True)
            self.assertFalse(result.is_done())
            self.assertEqual(2, result.get_result())

    def test_delay_call__below_max_response_time(self):
        with server_context(FooService(), max_response_time=2):
            client = create_client()
            result = client.delay_call(async_rpc=True)
            self.assertTrue(result.is_done())
            self.assertEqual(2, result.get_result())

    def test_no_delay_deferred_call(self):
        with server_context(FooService(), max_response_time=1):
            client = create_client()
            result = client.no_delay_deferred_call(async_rpc=True)
            self.assertFalse(result.is_done())
            self.assertEqual(3, result.get_result())

    def test_delay_deferred_call__below_max_response_time(self):
        with server_context(FooService(), max_response_time=2):
            client = create_client()
            result = client.delay_deferred_call(async_rpc=True)
            self.assertFalse(result.is_done())
            self.assertEqual(4, result.get_result())

    def test_delay_deferred_call__above_max_response_time(self):
        with server_context(FooService(), max_response_time=0.5):
            client = create_client()
            result = client.delay_deferred_call(async_rpc=True)
            self.assertFalse(result.is_done())
            self.assertEqual(4, result.get_result())

    def test_auto_timeout_client__timeout_implicilty_found(self):
        with server_context(FooService(), max_response_time=0.5):
            client = AutoTimeoutClient(ZeroRPCClientTransport.create_tcp(8192))
            client.no_delay_call()
            self.assertEqual(0.5, client.get_server_max_response_time())

    def test_auto_timeout_client__timeout_explicitly_found(self):
        with server_context(FooService(), max_response_time=0.5):
            client = AutoTimeoutClient(ZeroRPCClientTransport.create_tcp(8192))
            self.assertEqual(0.5, client.get_server_max_response_time())

    def test_auto_timeout_client__short_timeout_on_stuck_server(self):
        import time
        from threading import Event

        wait_for_start = Event()
        wait_for_close = Event()

        def thread_server(wait_for_start, wait_for_close):
            try:
                print(("starting server, hub: {}".format(gevent.hub.get_hub())))
                with logbook.NullHandler().applicationbound():
                    with server_context(FooService(), max_response_time=0.1):
                        print("server started.")
                        wait_for_start.set()
                        while not wait_for_close.is_set():
                            gevent.sleep(0.1)
            except:
                import traceback
                traceback.print_exc()

        from gevent.threadpool import ThreadPool

        t = ThreadPool(1)
        t.size = 1
        t.spawn(thread_server, wait_for_start, wait_for_close)

        try:
            print(("starting client, hub: {}".format(gevent.hub.get_hub())))
            client = AutoTimeoutClient(ZeroRPCClientTransport.create_tcp(8192), timeout_calc_func=lambda n: n * 2)
            wait_for_start.wait()
            print("client started.")
            t1 = time.time()
            self.assertRaises(TimeoutExpired, client.stuck_call)
            t2 = time.time()
            # This test should always pass although we're dealing with timing and non-deterministic measures since
            # stuck_call() is stuck for an entire second while we're comparing time to 0.2 (almost an order of a
            # magnitude)
            self.assertAlmostEqual(0.2, t2 - t1, delta=0.2)
        finally:
            wait_for_close.set()
            t.join()
