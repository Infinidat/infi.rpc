#
# Copyright 2013 Infinidat Ltd. All rights reserved.
# Use is subject to license terms.
#
import sys
from gevent import sleep
from infi.pyutils.lazy import cached_method
from infi.pyutils.contexts import contextmanager
from infi.pyutils.decorators import _ipython_inspect_module, wraps

from .. import errors
from .utils import SelfLoggerMixin
from .protocol import (RPCCall, encode_rpc_call, decode_rpc_result, RPC_RESULT_CODE_SUCCESS, RPC_RESULT_CODE_ERROR,
                       RPC_RESULT_CODE_DEFERRED)

POLL_SLEEP_INTERVAL_IN_SECONDS = 0.1


class DeferredResult(object):
    """Abstract object for a deferred result."""

    def poll(self):
        """
        Polls for the result.

        :return: `True` if there is a result, `False` if not.
        """
        raise NotImplementedError()

    def is_done(self, poll=False):
        """
        Returns `True` if there is a result, can optionally poll.
        """
        raise NotImplementedError()

    def get_result(self):
        """
        Blocks for a result and returns it or raises an error if the result was an error.
        """
        raise NotImplementedError()


class ImmediateResult(DeferredResult):
    """Deferrable that already contains a result."""

    def __init__(self, success, result):
        super(ImmediateResult, self).__init__()
        self.success = success
        self.result = result

    def poll(self):
        return True

    def is_done(self, poll=False):
        return True

    def get_result(self):
        return self._result()

    def _result(self):
        if self.success:
            return self.result
        else:
            raise errors.RPCException.from_dict(self.result)


class AsyncDeferredResult(DeferredResult):
    """Deferred result that polls for the result."""

    def __init__(self, client, request_id, poll_sleep_interval=POLL_SLEEP_INTERVAL_IN_SECONDS):
        self.client = client
        self.request_id = request_id
        self.poll_sleep_interval = poll_sleep_interval
        self.result = None
        self.exception = None
        self.finished = False
        self.success = None

    def poll(self):
        """
        Polls for the result from the server.

        :return: `True` if there is a result, `False` if not.
        """
        if self.finished:
            return True

        server_response = self.client.query_async_request(self.request_id)
        if server_response['code'] == RPC_RESULT_CODE_DEFERRED:
            return False

        self.finished = True
        self.success = server_response['code'] == RPC_RESULT_CODE_SUCCESS
        if self.success:
            self.result = server_response['result']
        else:
            self.exception = server_response['exception']

        return self.finished

    def is_done(self, poll=False):
        """
        Returns `True` if there is a result, can optionally poll.
        """
        if poll:
            return self.poll()
        else:
            return self.finished

    def get_result(self):
        """
        Blocks for a result and returns it or raises an error if the result was an error.
        """
        if self.finished:
            return self._result()
        while not self.poll():
            sleep(self.poll_sleep_interval)
        return self._result()

    def _result(self):
        if self.success:
            return self.result
        else:
            raise errors.RPCException.from_dict(self.exception)

    def __repr__(self):
        return "{}.{}(request_id={}, client={})".format(self.__class__.__module__, self.__class__.__name__,
                                                        self.request_id, self.client)

    def __str__(self):
        return repr(self)


class Client(SelfLoggerMixin):  # pragma: no cover
    """
    RPC client that supports long asynchronous operations.

    :param transport: transport object to use (e.g. :py:class:`ZeroRPCClientTransport`)
    """
    def __init__(self, transport):
        self._cache = dict()
        self._transport = transport

    def call(self, method_name, *args, **kwargs):
        try:
            async = kwargs.pop('async_rpc', False)

            self._transport.connect()

            rpc_call = RPCCall(method_name, args, kwargs)
            arg = encode_rpc_call(rpc_call)

            self.log_debug("sending RPC request {}".format(rpc_call))
            result = self._transport.call(arg)

            return self._handle_rpc_result(result, rpc_call, async)
        except errors.TimeoutExpired:
            exc_info = sys.exc_info()
            self.log_debug("got {}: {}".format(exc_info[1].__class__.__name__, exc_info[1].message))
            try:
                self._transport.close()
            except:
                close_exc_info = sys.exc_info()
                self.log_debug("encountered {} error on socket close: {}".format(close_exc_info[1].__class__.__name__,
                                                                                 close_exc_info[1].message))
            raise exc_info[0], exc_info[1], exc_info[2]

    def _handle_rpc_result(self, result_dict, rpc_call, async=False):
        try:
            code, result = decode_rpc_result(result_dict)
        except (errors.InvalidRPCMethod, errors.InvalidCallArguments), error:
            self.log_error("sent invalid RPC call {}: {}".format(rpc_call, error.message))
            self._handle_invalid_rpc_exception(error)
            assert False  # should never reach here since _handle_invalid_rpc_exception will raise or abort
            return

        self.log_debug("got RPC response for {}: {}".format(rpc_call, result_dict))
        if code in (RPC_RESULT_CODE_SUCCESS, RPC_RESULT_CODE_ERROR):
            deferred = ImmediateResult(code == RPC_RESULT_CODE_SUCCESS, result)
        else:
            deferred = self._create_deferred_result(result)

        if async:
            return deferred
        else:
            return deferred.get_result()

    def _create_deferred_result(self, result):
        return AsyncDeferredResult(self, result)

    def _handle_invalid_rpc_exception(self, error):
        _type, value, traceback = sys.exc_info()
        raise _type, value, traceback

    @cached_method
    def _get_rpc_method_names(self):
        return self.get_rpc_method_names()

    @cached_method
    def _get_rpc_ipython_argspec(self, method_name):
        return self.get_rpc_ipython_argspec(method_name)

    def __getattr__(self, method_name):
        attr = lambda *args, **kwargs: self.call(method_name, *args, **kwargs)
        attr.__name__ = "<bound method {}.{} of {!r}>".format(self.__class__.__name__, method_name, self)
        attr.rpc_method_name = method_name
        attr.rpc_call = True
        return attr

    def __repr__(self):
        return "<infi.rpc:{} 0x{:x}/{}>".format(self.__class__.__name__, id(self), repr(self._transport))

    def __str__(self):
        return repr(self)

    def __dir__(self):
        return dir(super(Client, self)) + self._get_rpc_method_names()


class IPython_Mixin(object):
    """Mixin that shortcircuits IPython methods called when hitting <tab> so they won't get sent to the remote end."""
    def _getAttributeNames(self):  # pragma: no cover
        return dir(self)

    def trait_names(self):  # pragma: no cover
        return []


def strictify(client):
    """A client that dies on invalid RPC calls, useful when building a strict/production system"""
    def _handle_invalid_rpc_exception(error):
        # FIXME
        from izbox.utils import die_now_and_dont_look_back
        reason = "invalid RPC exception: {}".format(error)
        die_now_and_dont_look_back(reason=reason, exc_info=sys.exc_info())
    client._handle_invalid_rpc_exception = _handle_invalid_rpc_exception


def mul_by_two_or_min_one(n):
    """Simple timeout calculation: multiple the max response time by 2 or at least a minimum of 1 second."""
    return max(n * 2, 1)


class AutoTimeoutClient(Client):
    """
    RPC client that supports long asynchronous operations and negotaties the timeout for a request with the server.

    :param transport: transport object to use (e.g. :py:class:`ZeroRPCClientTransport`)
    """

    def __init__(self, transport, timeout_calc_func=mul_by_two_or_min_one):
        super(AutoTimeoutClient, self).__init__(transport)
        self._timeout_calc_func = timeout_calc_func
        self._server_max_response_time = None
        self._auto_timeout_set = False

    def call(self, method_name, *args, **kwargs):
        if not self._auto_timeout_set:
            max_response_time = self.get_server_max_response_time()
            if max_response_time != -1:
                new_timeout = self._timeout_calc_func(max_response_time)
                self._transport.set_timeout(new_timeout)
                self._auto_timeout_set = True
        return super(AutoTimeoutClient, self).call(method_name, *args, **kwargs)

    def get_server_max_response_time(self):
        if self._server_max_response_time is not None:
            return self._server_max_response_time
        try:
            self._server_max_response_time = super(AutoTimeoutClient, self).call('get_rpc_max_response_time')
        except errors.InvalidRPCMethod:
            self._server_max_response_time = -1
        return self._server_max_response_time


@contextmanager
def patched_ipython_getargspec_context(client):
    original = _ipython_inspect_module.getargspec

    @wraps(original)
    def patched(func):
        if hasattr(func, "rpc_call") and getattr(func, "rpc_call"):
            return client.get_rpc_ipython_argspec(getattr(func, "rpc_method_name", func.__name__))
        return original(func)
    _ipython_inspect_module.getargspec = patched
    _ipython_inspect_module.getargspec = patched
    try:
        yield
    finally:
        _ipython_inspect_module.getargspec = original
