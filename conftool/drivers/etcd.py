import etcd
import urlparse
import json
from conftool import drivers


class Driver(drivers.BaseDriver):
    lock_ttl = 60

    def __init__(self, config):
        super(Driver, self).__init__(config)
        host_list = []
        self.locks = {}
        for el in config.hosts:
            h, p = urlparse.urlparse(el).netloc.split(':')
            host_list.append((h, int(p)))
        proto = urlparse.urlparse(config.hosts[0]).scheme
        # since we're using a tuple, we need this.
        config.driver_options['allow_reconnect'] = True
        self.client = etcd.Client(host=tuple(host_list),
                                  protocol=proto,
                                  **config.driver_options)
        super(Driver, self).__init__(config)

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
        res = self._fetch(key, quorum=True)
        if res is not None:
            old_value = json.loads(res.value)
            old_value.update(value)
            res.value = json.dumps(old_value)
            return self._data(self.client.update(res))
        else:
            val = json.dumps(value)
            self.client.write(key, val, prevExist=False)

    @drivers.wrap_exception(etcd.EtcdException)
    def ls(self, path):
        key = self.abspath(path)
        try:
            res = self.client.read(key)
        except etcd.EtcdException:
            raise ValueError("{} is not a directory".format(key))
        fullpath = key + '/'
        return [(el.key.replace(fullpath, ''), self._data(el))
                for el in res.leaves
                if el.key != key]

    @drivers.wrap_exception(etcd.EtcdException)
    def delete(self, path):
        key = self.abspath(path)
        self.client.delete(key)

    def _fetch(self, key, **kwdargs):
        try:
            return self.client.read(key, **kwdargs)
        except etcd.EtcdKeyNotFound:
            return None

    def _data(self, etcdresult):
        if etcdresult is None or etcdresult.dir:
            return None
        return json.loads(etcdresult.value)

    def get_lock(self, path):
        name = path.replace('/', '-')
        if name not in self.locks:
            self.locks[name] = etcd.Lock(self.client, name)
        self.locks[name].acquire(lock_ttl=self.lock_ttl)
        if self.locks[name].is_acquired:
            return self.locks[name]
        else:
            return False

    def release_lock(self, path):
        name = path.replace('/', '-')
        # we can't remove a lock that was not set by us
        if name not in self.locks:
            return False
        self.locks[name].release()
        del self.locks[name]
        return True

    def watch_lock(self, path):
        name = path.replace('/', '-')
        l = etcd.Lock(self.client, name)
        try:
            r = self.client.read(l.path)
            return bool(r._children)
        except etcd.EtcdKeyNotFoundErrror:
            return False
