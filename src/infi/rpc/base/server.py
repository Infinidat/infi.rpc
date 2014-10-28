#
# Copyright 2013 Infinidat Ltd. All rights reserved.
# Use is subject to license terms.
#
from __future__ import absolute_import
import sys
import functools
import gevent
import gevent.event
from time import time
from inspect import getcallargs
from infi.logging.plugins.request_id_tag import get_tag as get_request_id_tag, request_id_tag_context
from infi.gevent_utils.gevent_loop import GeventLoop

from ..errors import InvalidCallArguments, InvalidAsyncToken
from .protocol import (encode_rpc_result_exc_info, encode_rpc_result_success, encode_rpc_result_deferred,
                       encode_rpc_result_invalid_rpc_method_exc_info, decode_rpc_call)
from .service import is_rpc_deferred_method, is_rpc_immediate_method
from .utils import SelfLoggerMixin


RESULT_GARBAGE_COLLECTOR_INTERVAL = 5
INTERVAL_TO_KEEP_RESULT_IN_SECONDS = 5
MAX_RESPONSE_TIME = 0.5


def validate_call_arguments(func, args, kwargs):
    """
    Makes sure that ``args`` and ``kwargs`` satisfy ``func``'s signature.

    :raises InvalidCallArguments: if ``func``'s signature is not compatible with ``args`` and ``kwargs``
    """
    try:
        getcallargs(func, *args, **kwargs)
    except Exception, error:
        raise InvalidCallArguments(str(error))


class ServerBase(SelfLoggerMixin):  # pragma: no cover
    """
    Base class for an RPC server.

    :param transport: a transport layer object (e.g. :py:class:`ZeroRPCServerTransport` instance)
    :param service: a service object (e.g. a child instance of :py:class:`ServiceBase`)
    """
    def __init__(self, transport, service):
        self._transport = transport
        self._service = service
        self._handler_map = dict()
        self._shutdown_event = gevent.event.Event()

    def _build_handler_map(self):
        method_names = self._service._get_rpc_method_names()
        for name in method_names:
            method = getattr(self._service, name)
            handler = self._map_method_to_handler(name, method)
            self._set_handler_method_map(handler, method, name)

    def _set_handler_method_map(self, handler, method, name=None):
        if name is None:
            name = method.__name__
        self._handler_map[name] = (self._bind_handler_to_method(handler, method), method)

    def _bind_handler_to_method(self, handler, method):
        bound_handler = functools.partial(handler, method)
        functools.update_wrapper(bound_handler, method)
        return bound_handler

    def _map_method_to_handler(self, name, method):
        raise NotImplementedError()

    def bind(self):
        """Start accepting new RPCs. Also clears the `shutdown_event`."""
        self._shutdown_event.clear()
        self._build_handler_map()
        self._transport.bind(self._on_request)

    def unbind(self):
        """Stop accepting new RPCs. Requests that are still in process will not be cancelled."""
        self._transport.unbind()

    def request_shutdown(self):
        """
        Sets the ``_shutdown_event`` event that can also be queried by calling :py:meth:`is_shutdown_requested`.
        By itself it doesn't do anything more but subclasses can wait on the event to implement their own shutdown
        strategy.
        """
        self._shutdown_event.set()

    def is_shutdown_requested(self):
        """
        :return: `True` if a shutdown was requested.
        """
        return self._shutdown_event.is_set()

    def _on_request(self, arg):
        rpc_call = decode_rpc_call(arg)
        with request_id_tag_context(title=None, tag=rpc_call.request_id_tag):
            rpc_call.request_id_tag = get_request_id_tag()  # might get assigned if was None
            self.log_debug("received RPC request {}".format(rpc_call))

            handler, method = self._handler_map.get(rpc_call.method, (None, None))
            if handler is None:
                self.log_error("received invalid RPC method {}, returning error".format(rpc_call.method))
                return encode_rpc_result_invalid_rpc_method_exc_info(rpc_call.method)
            try:
                validate_call_arguments(method, rpc_call.args, rpc_call.kwargs)
            except InvalidCallArguments:
                self.log_error("received invalid RPC arguments for method {}, returning error".format(rpc_call.method))
                return encode_rpc_result_exc_info(sys.exc_info())

            result = handler(rpc_call)
            self.log_debug("replying to RPC request {} with {}".format(rpc_call, result))
            return result

    def _execute_call(self, method, rpc_call):
        with request_id_tag_context(title=None, tag=rpc_call.request_id_tag):
            try:
                result = method(*rpc_call.args, **rpc_call.kwargs)
                return encode_rpc_result_success(result)
            except BaseException:
                exc_info = sys.exc_info()
                self.log_exception("RPC call failed {}".format(rpc_call))
                return encode_rpc_result_exc_info(exc_info)


class SyncServer(ServerBase):
    """
    A server that executes every RPC synchronously, which means that the server will not return a response to the client
    until the request completes.

    Although it's very simple, for most implementations you probably want to use :py:class:`Server` instead since with
    this server the client can't tell if the server is stuck or the request is still in progress.

    :param transport: a transport layer object (e.g. :py:class:`ZeroRPCServerTransport` instance)
    :param service: a service object (e.g. a child instance of :py:class:`ServiceBase`)
    """
    def _map_method_to_handler(self, name, method):
        return self._execute_call


class AsyncRequest(object):
    QUEUED = 1
    PROCESSING = 2
    RESULT_AVAILABLE = 3

    def __init__(self, rpc_call):
        self.state = AsyncRequest.QUEUED
        self.rpc_call = rpc_call
        self.greenlet = None

    def spawn(self, method, args, kwargs):
        self.state = AsyncRequest.PROCESSING
        self.greenlet = gevent.spawn(method, *args, **kwargs)
        self.greenlet.link(self._result_available)

    def has_result(self):
        return self.state == AsyncRequest.RESULT_AVAILABLE

    def get_result(self):
        return self.greenlet.get(block=False)

    def wait(self, timeout):
        self.greenlet.join(timeout)

    def _result_available(self, _):
        self.state = AsyncRequest.RESULT_AVAILABLE
        self.finish_time = time()


class AsyncMixin(object):
    def __init__(self, result_garbage_collector_interval=RESULT_GARBAGE_COLLECTOR_INTERVAL,
                 interval_to_keep_result=INTERVAL_TO_KEEP_RESULT_IN_SECONDS):
        self._deferred_requests = dict()
        self._interval_to_keep_result = interval_to_keep_result
        self._result_garbage_collector = GeventLoop(result_garbage_collector_interval,
                                                    self.garbage_collect_deferred_results)

    def _find_or_spawn_async_request(self, method, call):
        async_request = self._deferred_requests.get(call.uuid, None)
        if async_request is None:
            async_request = AsyncRequest(call)
            self._deferred_requests[call.uuid] = async_request
            async_request.spawn(self._execute_call, [method, call], dict())
        return async_request

    def _async_handler(self, method, call):
        async_request = self._find_or_spawn_async_request(method, call)
        return self._build_async_response(async_request)

    def _query_async_request(self, uuid):
        async_request = self._deferred_requests.get(uuid, None)
        if async_request is None:
            raise InvalidAsyncToken(uuid)
        return self._build_async_response(async_request)

    def _set_query_async_request_to_handler_map(self):
        self._set_handler_method_map(self._execute_call, self._query_async_request, 'query_async_request')

    def _build_async_response(self, request):
        if request.has_result():
            del self._deferred_requests[request.rpc_call.uuid]
            try:
                return request.get_result()
            except BaseException:
                exc_info = sys.exc_info()
                return encode_rpc_result_exc_info(exc_info)
        else:
            return encode_rpc_result_deferred(request.rpc_call.uuid)

    def garbage_collect_deferred_results(self):
        """Removes unclaimed results that finished more than ``interval_to_keep_result`` seconds ago."""
        uuids_to_delete = set()
        now = time()
        for uuid, req in self._deferred_requests.iteritems():
            if req.state == AsyncRequest.RESULT_AVAILABLE and now > (req.finish_time + self._interval_to_keep_result):
                uuids_to_delete.add(uuid)
        for uuid in uuids_to_delete:
            del self._deferred_requests[uuid]

    def start_garbage_collect_deferred_results(self):
        """Starts the unclaimed results garbage collection greenlet"""
        self._result_garbage_collector.start()

    def stop_garbage_collect_deferred_results(self):
        """Stops the unclaimed results garbage collection greenlet"""
        self._result_garbage_collector.stop()

    def deferred_requests_count(self):
        """:return: count of deferred requests (in-progress and finished requests yet to be claimed by clients)"""
        return len(self._deferred_requests)

    def has_deferred_requests(self):
        """
        :return: ``True`` if there are active deferred requests (either in-progress or waiting a client to poll their
                 result)
        """
        return bool(self._deferred_requests)

    def wait_for_empty_deferred_requests(self, timeout=None, poll_interval=0.1):
        """
        Waits for all deferred requests to complete and either get polled or expire.

        :param timeout: seconds to wait before giving up, or ``None`` to block forever
        :param poll_interval: how often to poll and check if all requests are done
        :return: ``True`` if all deferred requests completed and got polled or expired, ``False`` if there are still
                 active deferred requests.
        """
        if timeout is None:
            timeout = 86400 * 365  # 1 year - no one waits one year for a method.
        start_time = time()
        end_time = start_time + timeout
        while self.has_deferred_requests() and time() < end_time:
            gevent.sleep(poll_interval)
            self.garbage_collect_deferred_results()  # manually try to do garbage collection to speed things up.
        return not self.has_deferred_requests()


class AsyncServer(ServerBase, AsyncMixin):
    """
    A server that executes every RPC asynchronously, which means for every RPC it will immediately return a deferred
    result with a token so the client can use to poll for the actual result.

    Since this server *always* return a deferred result this may cause unnecessary round-trips if the RPC never blocks
    (for example, a `ping` call).

    For most implementations, you probably want to use :py:class:`Server` instead.


    :param transport: a transport layer object (e.g. :py:class:`ZeroRPCServerTransport` instance)
    :param service: a service object (e.g. a child instance of :py:class:`ServiceBase`)
    :param result_garbage_collector_interval: how often (in seconds) should a garbage collector run and remove
                                              unclaimed results (response for a request that the client didn't
                                              poll to get)
    :param interval_to_keep_result: how much time (in seconds) should keep an unclaimed result. Since the clients
                                    poll to get the result, the interval should be greater than the client's poll
                                    interval (usually twice the time of the client's poll interval).
    """
    def __init__(self, transport, service, result_garbage_collector_interval=RESULT_GARBAGE_COLLECTOR_INTERVAL,
                 interval_to_keep_result=INTERVAL_TO_KEEP_RESULT_IN_SECONDS):
        ServerBase.__init__(self, transport, service)
        AsyncMixin.__init__(self, result_garbage_collector_interval, interval_to_keep_result)
        self._set_query_async_request_to_handler_map()

    def _map_method_to_handler(self, name, method):
        if is_rpc_immediate_method(method):
            return self._execute_call
        return self._async_handler

    # FIXME do we want to provide this here on bind? should we offer new "start/stop" methods that combine these?
    def bind(self):
        """
        Start accepting new RPCs and the deferred results garbage collector greenlet.
        Also clears the `shutdown_event`.
        """
        super(AsyncServer, self).bind()
        self.start_garbage_collect_deferred_results()

    def unbind(self):
        """
        Stop accepting new RPCs and the deferred results garbage collector greenlet.
        Requests that are still in process will not be cancelled.
        """
        try:
            super(AsyncServer, self).unbind()
        finally:
            self.stop_garbage_collect_deferred_results()


class Server(AsyncServer):
    """
    A server that can handle synchronous RPCs and asynchronous RPCs and guarantee a maximum time before replying to
    a client.

    :param transport: a transport layer object (e.g. :py:class:`ZeroRPCServerTransport` instance)
    :param service: a service object (e.g. a child instance of :py:class:`ServiceBase`)
    :param result_garbage_collector_interval: how often (in seconds) should a garbage collector run and remove
                                              unclaimed results (response for a request that the client didn't
                                              poll to get)
    :param interval_to_keep_result: how much time (in seconds) should keep an unclaimed result. Since the clients
                                    poll to get the result, the interval should be greater than the client's poll
                                    interval (usually twice the time of the client's poll interval).
    :param max_response_time: how much time to block and wait for the service's method to return before returning
                              a deferred response.
    """
    def __init__(self, transport, service,
                 result_garbage_collector_interval=RESULT_GARBAGE_COLLECTOR_INTERVAL,
                 interval_to_keep_result=INTERVAL_TO_KEEP_RESULT_IN_SECONDS,
                 max_response_time=MAX_RESPONSE_TIME):
        AsyncServer.__init__(self, transport, service, result_garbage_collector_interval, interval_to_keep_result)
        self._max_response_time = max_response_time
        self._set_handler_method_map(self._execute_call, self.get_rpc_max_response_time, 'get_rpc_max_response_time')

    def _map_method_to_handler(self, name, method):
        if is_rpc_deferred_method(method):
            return self._async_handler

        if self._max_response_time is None or is_rpc_immediate_method(method):
            return self._execute_call
        else:
            return self._semi_async_handler

    def _semi_async_handler(self, method, call):
        async_request = self._find_or_spawn_async_request(method, call)
        if async_request.state == AsyncRequest.RESULT_AVAILABLE:
            return self._build_async_response(async_request)
        async_request.wait(self._max_response_time)
        return self._build_async_response(async_request)

    def get_rpc_max_response_time(self):
        return self._max_response_time
