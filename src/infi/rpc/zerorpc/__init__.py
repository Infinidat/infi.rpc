#
# Copyright 2013 Infinidat Ltd. All rights reserved.
# Use is subject to license terms.
#
from __future__ import absolute_import

from .client import ZeroRPCClientTransport
from .server import ZeroRPCServerTransport

__all__ = ['ZeroRPCClientTransport', 'ZeroRPCServerTransport']


##
# Monkey patching zerorpc to fix two problems:
# - gevent error printing to stderr
# - Event repr bloated to an enormous size
def monkey_patch_zerorpc():
    def zerorpc_event_repr(self):
        try:
            # the __str__ method of zerorpc.Event is actually more useful than __repr__ as it does not override it
            return str(self)
        except:
            object.__repr__(self)

    # zerorpc creates instances of Event so deep, there's no better way than this
    import zerorpc
    zerorpc.Event.__repr__ = zerorpc_event_repr
    zerorpc.gevent_zmq.logger.error = lambda *args, **kwargs: None  # it prints to stderr two known issues

monkey_patch_zerorpc()
