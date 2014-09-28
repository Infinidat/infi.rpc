#
# Copyright 2013 Infinidat Ltd. All rights reserved.
# Use is subject to license terms.
#
from __future__ import absolute_import
import zmq
import zerorpc
import logbook
from infi.logging.plugins.request_id_tag import request_id_tag
from infi.gevent_utils.safe_greenlets import safe_spawn
from gevent import sleep

from .. import base

# FIXME
from gevent import spawn as spawn_silent


ANYHOST = "0.0.0.0"

logger = logbook.Logger("infi.rpc")


class _ZeroRPCServer(zerorpc.Server, base.SelfLoggerMixin):
    def __init__(self, address, callback, name=None, context=None, pool_size=None):
        zerorpc.Server.__init__(self, dict(on_call=callback), name, context, pool_size)
        self._address = address

        zerorpc.Server.bind(self, self._address)

        # when we go down, we want to drop all the packets in the air
        self._events.setsockopt(zmq.LINGER, 0)

        # zerorpc.Server.run blocks, so we do what it does except for the blocking part
        self._acceptor_task = safe_spawn(self._acceptor)

    @request_id_tag(tag="acceptor")
    def _acceptor(self):
        while True:
            initial_event = self._multiplexer.recv()
            self._task_pool.add(spawn_silent(self._async_task, initial_event))

    # FIXME
    # @die_on_greenlet_exceptions
    def _async_task(self, initial_event):
        # We had to replace zerorpc's _async_task implementation due to two reasons:
        # 1. Original implementation doesn't handle exceptions like we want, specifically in its response-builder
        #    code.
        # 2. We don't want heartbeats because zerorpc's heartbeat implementation may cause active requests in the server
        #    to get killed (they are greenlets) in middle of processing if the heartbeat detects a lost peer.
        channel = self._multiplexer.channel(initial_event)
        bufchan = zerorpc.BufferedChannel(channel)
        event = bufchan.recv()
        try:
            self._context.hook_load_task_context(event.header)
            functor = self._methods.get(event.name, None)
            if functor is not None:
                functor.pattern.process_call(self._context, bufchan, event, functor)
            else:
                self.log_debug("invalid RPC method received: {}".format(event.name))
                result = base.encode_rpc_result_invalid_rpc_method_exc_info(event.name)
                reply_event = bufchan.create_event('OK', (result,), self._context.hook_get_task_context())
                self._context.hook_server_after_exec(event, reply_event)
                bufchan.emit_event(reply_event)
        except:
            self.log_exception("unhandled exception in zerorpc transport while handling event {}".format(event))
            raise
        finally:
            bufchan.close()

    def __str__(self):
        return repr(self)

    def __repr__(self):
        return "<{}.{}({})>".format(self.__class__.__module__, self.__class__.__name__,
                                    self._address if self._address else "unbound")


class ZeroRPCServerTransport(base.ServerTransport):
    """
    Transport layer implementation using ZeroRPC. We delegate almost everything to our ``_ZeroRPCServer``
    implementation.
    """

    @classmethod
    def create_tcp(cls, port, host=ANYHOST, *args, **kwargs):
        # One would say that 0.0.0.0 is too open but we'd like to be able to do RPC from outside the system for tests.
        # In the field we will have ipfilter blocking connections from outside the system.
        return ZeroRPCServerTransport("tcp://{}:{}".format(host, port), *args, **kwargs)

    def __init__(self, address, name=None, context=None, pool_size=None):
        self.address = address
        self.name = name
        self.context = context
        self.pool_size = pool_size
        self.zerorpc = None

    def bind(self, callback):
        self.zerorpc = _ZeroRPCServer(self.address, callback, self.name, self.context, self.pool_size)

    def unbind(self):
        if self.zerorpc:
            self.zerorpc.close()
            self._zmq_error_workaround()
            self.zerorpc = None

    def _zmq_error_workaround(self):
        # See https://github.com/zeromq/pyzmq/issues/129
        # Traceback (most recent call last):
        #   File "/Users/guy/gitserver/izbox/src/izbox/rpc/tests.py", line 24, in test_up_down_loop
        #     server.setup()
        #   File "/Users/guy/gitserver/izbox/src/izbox/rpc/zerorpc.py", line 23, in setup
        #     super(Server, self).bind("tcp://127.0.0.1:{}".format(self._port))
        #   File ".../site-packages/zerorpc-0.4.1-py2.7.egg/zerorpc/socket.py", line 43, in bind
        #     return self._events.bind(endpoint, resolve)
        #   File ".../site-packages/zerorpc-0.4.1-py2.7.egg/zerorpc/events.py", line 218, in bind
        #     r.append(self._socket.bind(endpoint_))
        #   File "socket.pyx", line 465, in zmq.core.socket.Socket.bind (zmq/core/socket.c:4749)
        # ZMQError: Address already in use
        sleep(0.05)
