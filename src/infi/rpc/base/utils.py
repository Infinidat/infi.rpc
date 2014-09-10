from logbook import Logger

logger = Logger('infi.rpc')


class SelfLoggerMixin(object):
    def log_debug(self, format, *args, **kwargs):
        self.get_logger().debug("{} {}".format(self, format), *args, **kwargs)

    def log_error(self, format, *args, **kwargs):
        self.get_logger().error("{} {}".format(self, format), *args, **kwargs)

    def log_exception(self, format, *args, **kwargs):
        self.get_logger().exception("{} {}".format(self, format), *args, **kwargs)

    def get_logger(self):
        return logger


def format_request(method, args, kwargs):
    return "{}(*{}, **{})".format(method, args, kwargs)
