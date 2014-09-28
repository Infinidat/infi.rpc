#
# Copyright 2013 Infinidat Ltd. All rights reserved.
# Use is subject to license terms.
#
from __future__ import absolute_import
import types
from gevent.lock import RLock
from infi.pyutils.decorators import wraps

from ..errors import InvalidRPCMethod
from .utils import SelfLoggerMixin


def rpc_call(func):
    """
    Decorator wrapping an RPC method that marks it as such (an RPC method). Use this decorator to mark which methods
    in a service should be exposed as RPC methods.
    """
    @wraps(func)
    def decorator(*args, **kwargs):
        return func(*args, **kwargs)
    decorator.rpc_call = True
    return decorator


def rpc_deferred(func):
    """
    Decorator wrapping an RPC method that marks it as a method that will most likely block and thus the server should
    immediately return a deferred result and not wait.
    """
    decorator = rpc_call(func)
    decorator.rpc_deferred = True
    return decorator


def rpc_immediate(func):
    """Decorator wrapping an RPC method that marks it as a method that will always return a result without blocking."""
    decorator = rpc_call(func)
    decorator.rpc_immediate = True
    return decorator


def is_rpc_deferred_method(func):
    return getattr(func, 'rpc_deferred', False)


def is_rpc_immediate_method(func):
    return getattr(func, 'rpc_immediate', False)


def _is_rpc_call_function(func):
    return getattr(func, 'rpc_call', False)


def _is_rpc_call_method(method):
    return isinstance(method, types.MethodType) and _is_rpc_call_function(method.__func__)


class ServiceBase(SelfLoggerMixin):
    """
    Base class for an RPC service. A service is a logical unit that exposes an RPC API.

    To create a service, you need to inherit from this class or other classes such as
    :py:class:`ServiceWithSynchronized` and decorate the methods you want to expose.

    For example::

        class MyService(infi.rpc.ServiceBase):
            @rpc_call
            def my_rpc_exposed_method(self, my_arg):
                return 42

    To expose the service as a server, see the :ref:`Server` class for example.
    """

    @rpc_call
    def get_rpc_method_names(self):
        """
        Provides introspection information to the client side.

        :return: list of callable RPC method names
        :rtype: list of strings
        """
        return self._get_rpc_method_names()

    @rpc_call
    def get_rpc_ipython_argspec(self, method_name):
        """
        Provides introspection information about an RPC method to clients that use IPython.

        :param method_name: method name string
        :return: IPython's getargspec result
        :raises InvalidRPCMethod: if the method is not an RPC method
        """
        from infi.pyutils.decorators import _ipython_inspect_module
        try:
            method = getattr(self, method_name)
        except AttributeError:
            raise InvalidRPCMethod(method_name)

        if not _is_rpc_call_method(method):
            raise InvalidRPCMethod(method_name)

        return _ipython_inspect_module.getargspec(method)

    @rpc_call
    def ping(self):
        """RPC method to just ping the service."""
        pass

    def _get_rpc_method_names(self):
        """
        Override this method to provide a custom list of RPC-exposed method names.

        :return: list of exposed RPC method names
        :rtype: list of strings
        """
        return [name for name in dir(self) if _is_rpc_call_method(getattr(self, name))]


class SynchronizedMixin(object):
    def __init__(self):
        self.synchronized_mutex = RLock()


def synchronized(func):
    """
    Decorator that synchronizes execution of all the `synchronized` decorated methods.
    This is useful if there are methods in the service that should not execute in parallel.

    .. note::
        To support synchronized methods, inherit from :py:class:`ServiceWithSynchronized` instead of
        :py:class:`ServiceBase`.
    """
    @wraps(func)
    def decorator(*args, **kwargs):
        if not args or not isinstance(args[0], SynchronizedMixin):
            raise ValueError("method {} if not part of a Synchronized service".format(func))
        with args[0].synchronized_mutex:
            return func(*args, **kwargs)
    return decorator


class ServiceWithSynchronized(ServiceBase, SynchronizedMixin):
    """
    Adds support for synchronizing RPC method calls.

    When you need to ensure that some of the RPC methods will not execute in parallel (e.g. synchronize file writes) use
    this as a base class and decorate the methods with the :py:func:`synchronized`.

    For example::

        class FileLogger(infi.rpc.ServiceWithSynchronized):
            @rpc_call
            @synchronized
            def write_log(self, message):
                ...

            @rpc_call
            @synchronized
            def rotate(self):
                ...
    """
    def __init__(self, *args, **kwargs):
        ServiceBase.__init__(self)
        SynchronizedMixin.__init__(self)
