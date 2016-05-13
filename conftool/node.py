from conftool import _log, choice
from conftool.kvobject import Entity
from conftool.service import Service


class ServiceCache(object):
    """
    Cache class for services - this will make nodes fetch services
    once per run, esp in the syncer, instead of fetching them node-by-node.
    Since we need to refresh services before we refresh nodes, this is not
    going to cause us reading stale data.
    """
    services = {}

    @classmethod
    def get(cls, cluster, servname):
        key = "{}_{}".format(cluster, servname)
        if key not in cls.services:
            cls.services[key] = Service(cluster, servname)
        return cls.services[key]


class Node(Entity):

    _schema = {'weight': int, 'pooled': choice("yes", "no", "inactive")}
    _tags = ['dc', 'cluster', 'service']

    def __init__(self, datacenter, cluster, servname, host):
        self.service = ServiceCache.get(cluster, servname)
        super(Node, self).__init__(datacenter, cluster, servname, host)

    @classmethod
    def base_path(cls):
        return cls.config.pools_path

    def get_default(self, what):
        _log.debug("Setting default for %s", what)
        return self.service.get_defaults(what)
