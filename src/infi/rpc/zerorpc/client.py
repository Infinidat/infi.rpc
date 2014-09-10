#
# Copyright 2013 Infinidat Ltd. All rights reserved.
# Use is subject to license terms.
#
from __future__ import absolute_import
import sys
import zerorpc
import zmq
import gevent
from zerorpc.channel import BufferedChannel

from .. import base
from .. import errors

LOCALHOST = "127.0.0.1"
CLIENT_TIMEOUT_IN_SECONDS = 10.0


class _ZeroRPCClient(zerorpc.Client):
    """ZeroRPC's client with some changes to remove heartbeat implementation"""

    def __call__(self, method, *args, **kargs):
        # We modify zerorpc's __call__ method to remove the heartbeat feature since it may cause server-side requests
        # to get interrupted during processing if it detects a lost remote and it may also fail if the client and
        # server don't have the same heartbeat frequency set.
        #
        # The following code is taken from zerorpc/core.py:
        timeout = kargs.get('timeout', self._timeout)
        channel = self._multiplexer.channel()
        bufchan = BufferedChannel(channel, inqueue_size=kargs.get('slots', 100))

        xheader = self._context.hook_get_task_context()
        request_event = bufchan.create_event(method, args, xheader)
        self._context.hook_client_before_request(request_event)
        bufchan.emit_event(request_event)

        try:
            if kargs.get('async', False) is False:
                return self._process_response(request_event, bufchan, timeout)

            async_result = gevent.event.AsyncResult()
            gevent.spawn(self._process_response, request_event, bufchan, timeout).link(async_result)
            return async_result
        except:
            # XXX: This is going to be closed twice if async is false and
            # _process_response raises an exception. I wonder if the above
            # async branch can raise an exception too, if no we can just remove
            # this code.
            bufchan.close()
            raise


class ZeroRPCClientTransport(base.ClientTransport, base.SelfLoggerMixin):
    """
    Transport layer implementation using ZeroRPC.

    Since the protocol layer handles all the method and argument encapsulation we don't use ZeroRPC's method calling,
    instead we assume (from the client-side) there's a method called ``on_call`` on the server-side implementation and
    we call it with the encoded method call.
    """

    @classmethod
    def create_tcp(cls, port, host=LOCALHOST, *args, **kwargs):
        """Convenience method to create a client over TCP."""
        return ZeroRPCClientTransport("tcp://{}:{}".format(host, port), *args, **kwargs)

    def __init__(self, address, timeout=CLIENT_TIMEOUT_IN_SECONDS):
        self._address = address
        self._timeout = timeout
        self._zerorpc = None

    def connect(self):
        """
        If not already connected, creates a ZeroRPC client to the address specified in the constructor.
        The method is called by the higher layer before every RPC call.
        """
        if self._zerorpc:
            return
        try:
            self._zerorpc = _ZeroRPCClient(connect_to=self._address, timeout=self._timeout)
            self._zerorpc._events.setsockopt(zmq.LINGER, 0)  # when we teardown, we want to discard all messages
        except:
            self._zerorpc = None
            raise

    def close(self):
        """
        If a client exists, closes it and removes it.
        This method may be called when an error occured.
        """
        if not self._zerorpc:
            return
        try:
            self._zerorpc.close()
        finally:
            self._zerorpc = None

    def call(self, arg):
        """
        Calls the server-side transport by assuming an ``on_call`` method on the server-side.
        Translates ZeroRPC's timeout exception to ours.
        """
        try:
            return self._zerorpc.__call__('on_call', arg)
        except zerorpc.exceptions.TimeoutExpired, error:
            self.log_debug("got zerorpc.exceptions.TimeoutExpired: {}".format(error.message))
            try:
                self.close()
            except:
                exc_info = sys.exc_info()
                self.log_debug("encountered error on socket close: {}".format(exc_info[1].message))
            raise errors.TimeoutExpired(error.message)

    def set_timeout(self, timeout):
        """Sets the timeout to be used from here on when making (new) RPC calls."""
        if self._timeout != timeout:
            self._timeout = timeout
            if self._zerorpc:
                self.close()
                self.connect()

    def __repr__(self):
        return "<zerorpc {}[{}]>".format(self._address, "connected" if self._zerorpc else "not connected")

    def __str__(self):
        return repr(self)
