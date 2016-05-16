import functools
import os


class BackendError(Exception):
    pass


class NotFoundError(BackendError):
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

    def find_in_path(self, path, name):
        pass

    def all_keys(self, path):
        """
        Given a path, return all nodes beneath it as a list [tag1,...,name]

        This can be used to enumerate all objects, and then construct the object

        for args in objclass.backend.driver.all_keys(objclass):
            yield objclass(*args)

        """
        pass

    def all_data(self, path):
        """
        Given a path, return a list of tuples for all the objects under that
        path in the form [(relative_path1, data1), (relative_path2, data2), ...]
        """
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
