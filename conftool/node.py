import os
from conftool import KVObject, _log
from conftool.service import Service

def choice(*args):
    def is_in(x):
        if x not in args:
            raise ValueError("{} not in '{}'".format(x, ",".join(args)))
        return x
    return is_in


class Node(KVObject):

    _schema = {'weight': int, 'pooled': choice("yes", "no", "inactive")}
    _tags = ['dc', 'cluster', 'service']

    def __init__(self, datacenter, cluster, servname, host):
        self.base_path = self.config.pools_path
        self.service = Service(cluster, servname)
        self._key = self.kvpath(datacenter, cluster, servname, host)
        self.fetch()

    @property
    def key(self):
        return self._key

    def get_default(self, what):
        _log.debug("Setting default for %s", what)
        return self.service.get_defaults(what)

    @classmethod
    def dir(cls, dc, cluster, service):
        return os.path.join(cls.config.pools_path, dc,
                            cluster, service)
