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
        """
        Returns an absolute path for the key
        """
        if path.startswith('/'):
            return path
        else:
            return os.path.join(self.base_path, path)

    def is_dir(self, path):
        """
        Check if the path is a directory on the kv-store. Returns a boolean
        """

    def all_keys(self, path):
        """
        Given a path, return all nodes beneath it as a list [tag1,...,name]

        This can be used to enumerate all objects, and then construct the object

        for args in objclass.backend.driver.all_keys(objclass):
            yield objclass(*args)

        """

    def all_data(self, path):
        """
        Given a path, return a list of tuples for all the objects under that
        path in the form [(relative_path1, data1), (relative_path2, data2), ...]
        """

    def write(self, key, value):
        """
        Write the value `value` to key `key`.
        Should return a dict with the key value written
        """

    def delete(self, key):
        """
        Delete the key at `key`. Raises an exception on failure
        """

    def read(self, key):
        """
        Read the value at `key` to a dict. Raises an exception on failure
        """

    def ls(self, path):
        """
        returns a list of direct children of directory.
        """
        if not self.is_dir(path):
            raise ValueError(
                "{} is not a directory".format(self.abspath(path)))


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
