import os

from conftool import _log, node, service, yaml_safe_load
from conftool.kvobject import Entity, FreeSchemaEntity, JsonSchemaEntity
from conftool.types import get_validator, get_json_schema


def factory(name, defs):
    """
    Creates a class tailored to the interested entity
    based on the inputs
    """
    properties = {
        '_tags': defs['tags'],
        '_base_path': defs['path'],
        'depends': defs.get('depends', []),
        '_schema': {},
        '_default_values': {}
    }

    json_schema = defs.get('json_schema', False)
    if json_schema:
        cls = JsonSchemaEntity
        properties['loader'] = get_json_schema(json_schema)
    elif defs.get('free_form', False):
        cls = FreeSchemaEntity
    else:
        cls = Entity

    properties['_schema'] = {}
    properties['_default_values'] = {}

    for k, v in defs['schema'].items():
        if json_schema:
            # Validation is done with json schema
            properties['_schema'][k] = get_validator('any')
        else:
            properties['_schema'][k] = get_validator(v['type'])
        properties['_default_values'][k] = v['default']

    def base_path(cls):
        return cls._base_path

    def get_default(self, what):
        return self._default_values[what]

    properties['get_default'] = get_default
    properties['base_path'] = classmethod(base_path)
    return type(name, (cls,), properties)


class Schema(object):
    """
    Allows loading entities definitions from a file declaration
    """

    def __init__(self):
        self.entities = {}
        self.has_errors = False
        # Add the special entities that have dedicated classes
        self._add_default_entities()

    @classmethod
    def from_file(cls, filename):
        """
        Load a yaml file
        """
        instance = cls()
        if not os.path.isfile(filename):
            return instance

        data = yaml_safe_load(filename, default={})
        if not data:
            instance.has_errors = True
            return instance

        for objname, defs in data.items():
            try:
                _log.debug('Loading entity %s', objname)
                entity_name = objname.capitalize()
                entity = factory(entity_name, defs)
                instance.entities[objname] = entity
            except Exception as e:
                _log.error('Could not load entity %s: %s', objname,
                           e, exc_info=True)
                instance.has_errors = True
        return instance

    def _add_default_entities(self):
        self.entities['node'] = node.Node
        self.entities['service'] = service.Service
