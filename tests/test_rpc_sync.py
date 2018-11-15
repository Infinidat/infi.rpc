from unittest import TestCase
from infi.rpc import Client, SyncServer, ServiceBase, ZeroRPCClientTransport, ZeroRPCServerTransport, rpc_call


class FooService(ServiceBase):
    @rpc_call
    def foo(self):
        return 42


class SyncRPCTestCase(TestCase):
    def test_straightforward(self):
        try:
            server_transport = ZeroRPCServerTransport.create_tcp(8192)
            server = SyncServer(transport=server_transport, service=FooService())
            server.bind()

            client_transport = ZeroRPCClientTransport.create_tcp(8192)
            client = Client(client_transport)
            self.assertEqual(client.foo(), 42)
        finally:
            server.unbind()
