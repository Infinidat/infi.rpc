import jsonpickle
from sys import exc_info
from .json_traceback import format_tb


class RPCException(Exception):
    should_be_logged = True
    log_with_traceback = True

    def to_dict(self, with_traceback=None):
        return dict(pickled=jsonpickle.encode(self), message=self.message, args=self.args)

    @classmethod
    def from_dict(cls, result_dict):
        error = jsonpickle.decode(result_dict['pickled'])
        for key, value in result_dict.iteritems():
            if key == 'pickled':
                continue
            setattr(error, key, value)
        return error


class RPCUserException(RPCException):
    pass


class RPCFrameworkException(RPCException):
    pass


class RPCTransportException(RPCFrameworkException):
    pass


class TimeoutExpired(RPCTransportException):
    pass


class InternalServerError(RPCFrameworkException):
    def __init__(self, original_exception):
        super(InternalServerError, self).__init__("type={!r}, value={!r}".format(type(original_exception), original_exception))


class InvalidReturnValue(RPCFrameworkException):
    pass


class InvalidRPCMethod(RPCFrameworkException):
    should_be_logged = False


class InvalidCallArguments(RPCFrameworkException):
    should_be_logged = False


class InvalidAsyncToken(RPCFrameworkException):
    should_be_logged = False


# FIXME not sure we need the "NotSetup" errors anymore...
class ClientNotSetupError(RPCFrameworkException):
    def __init__(self):
        super(ClientNotSetupError, self).__init__("client.setup() was not called or closed and not setup again")


class ServerNotSetupError(RPCFrameworkException):
    def __init__(self):
        super(ServerNotSetupError, self).__init__("server.setup() was not called or closed and not setup again")


class RequestAbortedError(RPCFrameworkException):
    def __init__(self):
        super(RequestAbortedError, self).__init__("request aborted while being processed")
