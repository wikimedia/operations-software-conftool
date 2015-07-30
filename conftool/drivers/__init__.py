import os
import functools


class BackendError(Exception):
    pass


class BaseDriver(object):

    def __init__(self, config):
        self.base_path = os.path.join(config.namespace, config.api_version)

    def abspath(self, path):
        if path.startswith('/'):
            return path
        else:
            return os.path.join(self.base_path, path)

    def is_dir(self, path):
        pass

    def write(self, key, value):
        pass

    def delete(self, key):
        pass

    def read(self, key):
        pass

    def ls(self, path):
        """
        returns a list of direct children of directory.
        """
        if not self.is_dir(path):
            raise ValueError(
                "{} is not a directory".format(self.abspath(path)))

    def get_lock(self, path):
        pass

    def lock_exists(self, path):
        pass

    def release_lock(self, path):
        pass


def wrap_exception(exc):
    def actual_wrapper(fn):
        @functools.wraps(fn)
        def _wrapper(*args, **kwdargs):
            try:
                return fn(*args, **kwdargs)
            except exc as e:
                raise BackendError("Backend error: {}".format(e))
        return _wrapper
    return actual_wrapper
