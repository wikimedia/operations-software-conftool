from collections import defaultdict

from conftool import _log
from conftool.types import get_validator
from conftool.kvobject import Entity


class Node(Entity):
    _schema = {"weight": get_validator("int"), "pooled": get_validator("enum:yes|no|inactive")}
    _tags = ["dc", "cluster", "service"]
    _defaults = {"pooled": "inactive", "weight": 0}

    @classmethod
    def base_path(cls):
        return cls.config.pools_path

    def get_default(self, what):
        _log.debug("Setting default for %s", what)
        # Objects get created with a weight of 0 and pooled=inactive
        return self._defaults[what]

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
        return super().from_yaml(transformed)
