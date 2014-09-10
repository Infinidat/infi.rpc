.. infi.rpc documentation master file, created by
   sphinx-quickstart on Mon Aug 18 11:45:03 2014.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Welcome to infi.rpc's documentation!
====================================

`infi.rpc` is a lightweight, responsive, logically-asynchronous RPC implementation built on top of
`ZeroRPC <http://zerorpc.dotcloud.com/>`_ and `gevent <http://www.gevent.org/>`_.

What is it good for?

* Building a robust and reliable distributed application
* Support operations that can take a long time to complete (seconds, minutes, hours)
* Exposing an API that accepts and returns complex structures using a language-agnostic marshaller
  (`MessagePack <http://msgpack.org>`_)

What is it not good for?

* Exposing remote objects transparently or symmetrically (e.g. `RPyC <http://rpyc.readthedocs.org>`_)
* Serving gazillions requests per second or real-time systems (well, Python isn't the answer for these at any rate)


What does logically-asynchronous mean?
--------------------------------------
When we say logically-asynchronous we mean that although the RPC is driven by `ZeroRPC`'s request/response mechanism,
instead of waiting on a long request that may take seconds or even minutes to complete we return a "token" so the client
can poll to fetch the result. It also means that the async part is not on a network level, it's higher up.

This approach has several benefits:

* We don't depend on setting (or not setting) various network timeouts to handle different type of requests/processing
  (i.e. we don't need to set a minutes-long timeouts)
* We can "guarantee" responsiveness - the server can always send a response after a pre-configured amount of time
  (we put quotes on "guarantee" because Python and gevent cannot guarantee anything in terms of real-timeness)
* When a client receives a deferred reply, it knows the request was registered at the server

The library also provides a client implementation, so all this async behavior can be abstracted so you don't need to
worry about it 99% of the time (the remaining 1% is deciding on a `Shutdown Strategy`_).


Overview / Supporting Long Operations
=====================================
`infi.rpc` is built on top of `ZeroRPC <http://zerorpc.dotcloud.com/>`_. This means that the transport layer is
`ZeroMQ <http://zeromq.org/>`_ and marshalling is handled using `MessagePack`_.

`infi.rpc` can be used to implement remote operations that either take a short amount of time to complete (e.g. a few
millis or under a second) just like `ZeroRPC`, or a long amount of time (seconds, minutes or even hours).

Supporting long operations requires different handling than short operations. Several reasons for that are:

* Keeping an active connection for the duration of the operation may waste resources
* We may not want to keep the client process alive during the full length of the operation
* From the programmer's point of view, defining network timeouts on the client side to detect an unresponsive server
  in this case is highly error prone. Since some operations may be short and some may be long configuring a standard
  timeout on all operations can't be done, and changing the timeout per operation is risky.


By design, all requests in `infi.rpc` can return a `promise <http://en.wikipedia.org/wiki/Futures_and_promises>`_, which
we call a *deferred object*. This *deferred object* (or simply *deferred*) can then be used by the client to poll for
the operation's completion status.

When building an API, the server-side developer can rely on `infi.rpc` to decide when to return a *deferred*
(i.e. if the operation takes too much time to complete) or explicitly state which operations may need to block or take
time to complete and which operations will never block.

The client-side developer can either block on API method calls until completion or handle the polling on his or her own.


Shutdown Strategy
=================
Deciding on a shutdown strategy is always difficult to get right, code-wise and design-wise. There are several issues
that always come up and require a decision:

* Do I want to abort active requests or wait for their completion? If I abort I may lose data or create inconsistency
  but if I wait for active requests to complete I prolong the server shutdown time, sometimes to something unacceptable.
* When should I close the listening socket? If I close the socket when starting to shut down, clients may mistakenly
  assume the server is dead and may trigger an errornous failover. On the other hand, if I leave the socket open
  I need to tell new requests that the server is shutting down and not accept these requests.

While `infi.rpc` promotes server responsiveness, by the nature of its design another decision needs to be made when
it comes to deciding on a shutdown strategy:

  Say that I want a "graceful" shutdown, where in a synchronous implementation I'll wait till all active requests finish
  and their clients receive the result. In our case however, clients will receive a *deferred* (almost) immediately so
  to wait for a client to receive a result means to wait till the client polls for the *deferred* object's status.

Since there's no right or wrong here, `infi.rpc` lets the server-side developer decide on the strategy, or even
implement several different strategies side-by-side.


API Reference
=============
The public API is available here: :ref:`infi.rpc`.

Internal API
------------
* :ref:`infi.rpc.base`
* :ref:`infi.rpc.zerorpc`

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`