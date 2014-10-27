#
# Copyright 2013 Infinidat Ltd. All rights reserved.
# Use is subject to license terms.
#
import sys
from munch import munchify
from uuid import uuid4
from infi.logging.plugins.request_id_tag import get_tag as get_request_id_tag

from .. import json_traceback
from ..errors import RPCException, InvalidReturnValue, InvalidRPCMethod, InternalServerError
from .utils import format_request

RPC_RESULT_CODE_SUCCESS = 'success'
RPC_RESULT_CODE_DEFERRED = 'deferred'
RPC_RESULT_CODE_ERROR = 'error'
RPC_RESULT_CODES = (RPC_RESULT_CODE_SUCCESS, RPC_RESULT_CODE_DEFERRED, RPC_RESULT_CODE_ERROR)


class ServerTransport(object):
    """
    This is a bridge between the transport layer (say ZeroRPC) and the high level object layer on the server side.
    It basically provides two methods to start accepting requests and stop accepting requests: ``bind`` and ``unbind``.
    """
    def bind(self, callback):
        """
        Start accepting requests from the transport layer. ``callback`` is a method that receives a single dict argument
        and will decode our RPC layer and then encode the result using ``protocol``.
        """
        raise NotImplementedError()

    def unbind(self):
        """
        Stop accepting requests from the transport layer.
        """
        raise NotImplementedError()


class ClientTransport(object):
    """
    This is a bridge between the transport layer (say ZeroRPC) and the high level object layer on the client side.
    """
    def connect(self):
        raise NotImplementedError()

    def close(self):
        raise NotImplementedError()

    def call(self, arg):
        raise NotImplementedError()

    def set_timeout(self, timeout):
        raise NotImplementedError()


class RPCCall(object):
    def __init__(self, method, args, kwargs, uuid=None, request_id_tag=None):
        self.method = method
        self.args = args
        self.kwargs = kwargs
        self.uuid = uuid
        self.request_id_tag = request_id_tag
        self.formatted_request = format_request(method, args, kwargs)

    def __repr__(self):
        return "(uuid={}, request_id_tag={}) {}".format(self.uuid, self.request_id_tag, self.formatted_request)

    def __str__(self):
        return repr(self)


def encode_rpc_call(rpc_call):
    rpc_call.uuid = str(uuid4()) if rpc_call.uuid is None else rpc_call.uuid
    rpc_call.request_id_tag = get_request_id_tag() if rpc_call.request_id_tag is None else rpc_call.request_id_tag
    meta = dict(method=rpc_call.method, uuid=rpc_call.uuid, request_id_tag=rpc_call.request_id_tag)
    return [meta, rpc_call.args, rpc_call.kwargs]


def decode_rpc_call(arg):
    meta, args, kwargs = arg
    name = meta['method']
    uuid = meta.pop('uuid', None)
    request_id_tag = meta.pop('request_id_tag', None)
    return RPCCall(name, args, kwargs, uuid, request_id_tag)


def encode_rpc_result_success(result):
    return dict(code=RPC_RESULT_CODE_SUCCESS, result=result)


def encode_rpc_result_exc_info(exc_info, with_traceback=None):
    if isinstance(exc_info[1], RPCException):
        result = encode_rpc_result_exception(exc_info[1])
    else:
        result = encode_rpc_result_exception(InternalServerError(exc_info[1]))
    if with_traceback is True or (with_traceback is None and getattr(exc_info[1], 'log_with_traceback', False)):
        result['server_side_traceback'] = json_traceback.format_tb(exc_info[2])
    return result


def encode_rpc_result_invalid_rpc_method_exc_info(name):
    try:
        raise InvalidRPCMethod(name)
    except:
        exc_info = sys.exc_info()
    return encode_rpc_result_exc_info(exc_info)


def encode_rpc_result_exception(exception):
    assert isinstance(exception, RPCException)
    return dict(code=RPC_RESULT_CODE_ERROR, exception=exception.to_dict())

def encode_rpc_result_deferred(uuid):
    return dict(code=RPC_RESULT_CODE_DEFERRED, result=uuid)


def decode_rpc_result(result_dict):
    if not isinstance(result_dict, dict):
        raise InvalidReturnValue(result_dict)
    result = munchify(result_dict)  # for convenience
    code = result.get('code')
    if code not in RPC_RESULT_CODES:
        raise InvalidReturnValue(result)
    if code in (RPC_RESULT_CODE_DEFERRED, RPC_RESULT_CODE_SUCCESS):
        return code, result.result
    else:
        return code, result.exception
