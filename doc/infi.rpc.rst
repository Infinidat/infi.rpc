.. _infi.rpc:

***********************
The :mod:`infi.rpc` API
***********************

.. py:currentmodule:: infi.rpc

To use `infi.rpc` there are four type of objects you should be aware of:

* Service objects. A service is where you implement your business logic.
* Transport objects. A transport object is responsible for the actual communication (currently `zerorpc`).
* Server objects. A server uses the transport layer to pass RPCs to the service and handle the async parts.
* Client objects. A client uses the transport layer to connect to a server and pass calls to it.


What can I pass?
----------------
You can pass Python primitives as arguments (int, float, string, list, dict).


A simple example
----------------

Here's a simple example of how to use `infi.rpc`::

	class MyService(ServiceBase):
		@rpc_call  # this marks the method as exposed by infi.rpc
		def mul_by_2(self, n):
			return n * 2

		@rpc_deferred  # this marks the method as something that takes time
		def sleep(self, n):
			gevent.sleep(n)
			return True

	service = MyService()
	server_transport = ZeroRPCServerTransport("tcp://127.0.0.1:8888")
	server = Server(server_transport, service, max_response_time=1)  # always return after 1 second

	server.bind()  # start accepting new requests

	client_transport = ZeroRPCClientTransport("tcp://127.0.0.1:8888")
	client = AutoTimeoutClient(client_transport)

	client.mul_by_2(5)  # will return 10
	client.sleep(10)    # will wait for 10 seconds before returning

	result = client.sleep(10, async_rpc=True)  # will return a deferred result immediately from the server
	result.get_result()	                       # will wait until we have a result (10 seconds)


Service
=======
Service classes are what you inherit from to write your business logic. You then connect a service instance with a
server instance.

.. autoclass:: ServiceBase
	:members:

.. autoclass:: ServiceWithSynchronized
	:members:


RPC method decorators
---------------------
The RPC method decorators are used to expose methods through RPC by marking the methods as such.

.. note::

	It's important that the RPC method decorators will be the last wrappers used on the method, which means they should
	be the *first* decorator written.

	For example, **don't** do this::

		...
		@my_other_decorator  # this hides the fact the method should be exposed by RPC
		@rpc_call
		def foo(self, arg):
			pass
		...

	Do this instead::

		...
		@rpc_call
		@my_other_decorator
		def foo(self, arg):
			pass
		...

.. autofunction:: rpc_call

.. autofunction:: rpc_deferred

.. autofunction:: rpc_immediate

.. autofunction:: synchronized


Server
======

.. autoclass:: Server
	:members:
	:inherited-members:

.. autoclass:: SyncServer
	:members:
	:inherited-members:

.. autoclass:: AsyncServer
	:members:
	:inherited-members:


Client
======

.. autoclass:: Client
	:members:
	:inherited-members:

.. autoclass:: AutoTimeoutClient
	:members:
	:inherited-members:

.. autoclass:: AsyncDeferredResult
	:members:
	:inherited-members:


ZeroRPC Transport
=================

.. autoclass:: ZeroRPCClientTransport
	:members:
	:inherited-members:

.. autoclass:: ZeroRPCServerTransport
	:members:
	:inherited-members: