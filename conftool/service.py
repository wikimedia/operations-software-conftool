import os
from conftool import KVObject


class Service(KVObject):
    _schema = {'default_values': dict, 'datacenters': list}
    _tags = ['cluster']

    def __init__(self, cluster, name, **kwdargs):
        self._key = os.path.join(self.config.services_path, cluster, name)
        self._schemaless = kwdargs
        self.fetch()

    def get_default(self, what):
        """
        Default values for services have no meaning.
        """
        defaults = {
            'default_values': {'pooled': "no", "weight": 0},
            'datacenters': ['eqiad', 'codfw']
        }
        return defaults[what]

    @property
    def key(self):
        return self._key

    def get_defaults(self, what):
        return self.default_values[what]

    def _to_net(self):
        values = super(Service, self)._to_net()
        for k, v in self._schemaless.items():
            values[k] = v
        return values

    def _from_net(self, values):
        super(Service, self)._from_net(values)
        if values is None:
            return
        for key, value in values.items():
            if key not in self._schema:
                self._schemaless[key] = value

    def changed(self, data):
        return self._to_net() == data

    @classmethod
    def dir(cls, cluster):
        return os.path.join(cls.config.services_path, cluster)
#    def __getattr__(self, what):
        # Will raise a ValueError as expected
#        return self._schemaless(what)

#    def __setattr__(self, what, value):
#        self._schemaless[what] = value
