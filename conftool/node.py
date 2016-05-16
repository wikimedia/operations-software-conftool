from collections import defaultdict

from conftool import _log
from conftool.types import get_validator
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

    _schema = {
        'weight': get_validator('int'),
        'pooled': get_validator("enum:yes|no|inactive")
    }
    _tags = ['dc', 'cluster', 'service']
    depends = ['service']

    def __init__(self, datacenter, cluster, servname, host):
        self.service = ServiceCache.get(cluster, servname)
        super(Node, self).__init__(datacenter, cluster, servname, host)

    @classmethod
    def base_path(cls):
        return cls.config.pools_path

    def get_default(self, what):
        _log.debug("Setting default for %s", what)
        return self.service.get_defaults(what)

    @classmethod
    def from_yaml(cls, data):
        """
        Imports objects from a yaml file.

        Format is:
        dc:
          cluster:
            hostname:
              - serviceA
              - serviceB
        """
        transformed = defaultdict(dict)
        for dc, clusters in data.items():
            for cluster, hosts in clusters.items():
                transformed[dc][cluster] = defaultdict(list)
                for host, services in hosts.items():
                    for service in services:
                        transformed[dc][cluster][service].append(host)
        return super(Node, cls).from_yaml(transformed)
