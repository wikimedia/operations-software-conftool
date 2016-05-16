import yaml

from conftool import _log, node, service
from conftool.kvobject import Entity, FreeSchemaEntity
from conftool.types import get_validator


def factory(name, defs):
    """
    Creates a class tailored to the interested entity
    based on the inputs
    """

    if defs.get('free_form', False):
        cls = FreeSchemaEntity
    else:
        cls = Entity
    _schema = {}
    _default_values = {}
    for k, v in defs['schema'].items():
        _schema[k] = get_validator(v['type'])
        _default_values[k] = v['default']

    def base_path(cls):
        return cls._base_path

    def get_default(self, what):
        return self._default_values[what]

    return type(name, (cls,),
                {"get_default": get_default,
                 "_schema": _schema,
                 "depends": defs.get('depends', []),
                 "_tags": defs['tags'],
                 "_base_path": defs['path'],
                 "base_path": classmethod(base_path),
                 "_default_values": _default_values})


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
        try:
            with open(filename, 'r') as f:
                data = yaml.load(f)
            for objname, defs in data.items():
                try:
                    _log.debug("Loading entity %s", objname)
                    entity_name = objname.capitalize()
                    entity = factory(entity_name, defs)
                    instance.entities[objname] = entity
                except Exception as e:
                    _log.error("Could not load entity %s: %s", objname,
                               e, exc_info=True)
                    instance.has_errors = True
        except IOError:
            _log.info(
                "Could not open %s - only standard entities will be available",
                filename
            )
            # We do not signal we had an error here, as it might be a choice
        except Exception as e:
            _log.error("Unexpected error loading the schema: %s", e,
                       exc_info=True)
            instance.has_errors = True
        return instance

    def _add_default_entities(self):
        self.entities['node'] = node.Node
        self.entities['service'] = service.Service
