import json
import os

import etcd
import urllib3

from conftool import drivers, yaml_safe_load, _log

"""

This driver will look at the following config files:

* /etc/etcd/etcdrc

* ~/.etcdrc

* what specified in the conftool configuration as driver_options =>
  etcd_config_file or /etc/conftool/etcdrc

read them as YAML files, and then pass every config switch found in there
to python-etcd.
"""


def get_config(configfile):
    conf = {}
    # Find the home of the user we're sudoing as - if any.
    # By default, expanduser checks the HOME variable, which is not overwritten by sudo
    # if env_keep += HOME is set. So sudo confctl would end up reading the config files of the user
    # executing sudo and not those of the user it was sudoing to.
    run_as = os.environ.get("USER", "")
    user_home = os.path.expanduser("~{}".format(run_as))
    configfiles = ["/etc/etcd/etcdrc", os.path.join(user_home, ".etcdrc")]
    if configfile:
        configfiles.append(configfile)

    for filename in configfiles:
        if os.path.exists(filename):
            conf.update(yaml_safe_load(filename, default={}))
        else:
            _log.debug("Skipping nonexistent etcd config file: %s", filename)
    return conf


class Driver(drivers.BaseDriver):
    lock_ttl = 60

    def __init__(self, config):
        super().__init__(config)
        self.locks = {}
        configfile = config.driver_options.get("etcd_config_file", "/etc/conftool/etcdrc")
        driver_config = get_config(configfile)
        try:
            if config.driver_options.get("suppress_san_warnings", True):
                urllib3.disable_warnings(category=urllib3.exceptions.SubjectAltNameWarning)
        except AttributeError:
            _log.warning(
                "You are using a modern version of urllib3; "
                "please set suppress_san_warnings to false in your driver configuration."
            )

        self.client = etcd.Client(**driver_config)
        super().__init__(config)

    @drivers.wrap_exception(etcd.EtcdException)
    def is_dir(self, path):
        p = self.abspath(path)
        try:
            res = self.client.read(p)
            return res.dir
        except etcd.EtcdKeyNotFound:
            return False

    @drivers.wrap_exception(etcd.EtcdException)
    def read(self, path):
        key = self.abspath(path)
        res = self._fetch(key)
        return self._data(res)

    @drivers.wrap_exception(etcd.EtcdException)
    def write(self, path, value):
        key = self.abspath(path)
        try:
            res = self._fetch(key, quorum=True)
            old_value = json.loads(res.value)
            old_value.update(value)
            res.value = json.dumps(old_value)
            return self._data(self.client.update(res))
        except drivers.NotFoundError:
            val = json.dumps(value)
            self.client.write(key, val, prevExist=False)

    def ls(self, path, recursive=False):
        """Given a path, returns a tuple (key, data) for each value found"""
        objects = self._ls(path, recursive=recursive)
        fullpath = self.abspath(path) + "/"
        return [(el.key.replace(fullpath, ""), self._data(el)) for el in objects]

    def all_keys(self, path):
        # The full path we're searching in
        base_path = self.abspath(path) + "/"

        def split_path(p):
            """Strip the root path and normalize elements"""
            r = p.replace(base_path, "").replace("//", "/")
            return r.split("/")

        return [split_path(el.key) for el in self._ls(path, recursive=True) if not el.dir]

    def all_data(self, path):
        """Return a (path, object) tuple for all the objects"""
        base_path = self.abspath(path) + "/"
        return [
            (obj.key.replace(base_path, ""), self._data(obj))
            for obj in self._ls(path, recursive=True)
            if not obj.dir
        ]

    @drivers.wrap_exception(etcd.EtcdException)
    def _ls(self, path, recursive=False):
        key = self.abspath(path)
        try:
            res = self.client.read(key, recursive=recursive)
        except etcd.EtcdException:
            raise ValueError("{} is not a directory".format(key))
        return [el for el in res.leaves if el.key != key]

    @drivers.wrap_exception(etcd.EtcdException)
    def delete(self, path):
        key = self.abspath(path)
        self.client.delete(key)

    def _fetch(self, key, **kwdargs):
        try:
            return self.client.read(key, **kwdargs)
        except etcd.EtcdKeyNotFound:
            raise drivers.NotFoundError()

    def _data(self, etcdresult):
        if etcdresult is None or etcdresult.dir:
            return None
        try:
            return json.loads(etcdresult.value)
        except ValueError:
            raise drivers.BackendError(
                "The kvstore contains malformed data at key %s" % etcdresult.key
            )
