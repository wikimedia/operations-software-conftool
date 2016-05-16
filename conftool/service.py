from conftool.kvobject import FreeSchemaEntity
from conftool.types import get_validator


class Service(FreeSchemaEntity):
    _schema = {
        'default_values': get_validator('dict'),
        'datacenters': get_validator('list')
    }
    _tags = ['cluster']
    static_values = True

    @classmethod
    def base_path(cls):
        return cls.config.services_path

    def get_default(self, what):
        """
        Default values for services have no meaning.
        """
        defaults = {
            'default_values': {'pooled': "no", "weight": 0},
            'datacenters': ['eqiad', 'codfw']
        }
        return defaults[what]

    def get_defaults(self, what):
        return self.default_values[what]
