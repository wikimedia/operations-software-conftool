"""Simple conftool initialization class."""
from typing import Dict, Optional
from conftool import configuration, setup_irc
from conftool.kvobject import KVObject, Entity
from conftool.loader import Schema


class ObjectTypeError(Exception):
    """
    Exception raised whenever an inexistent object type is raised
    """


class ConftoolClient:
    """Class that simplifies initializing conftool with a schema."""

    def __init__(
        self,
        *,
        configfile: Optional[str] = None,
        config: Optional[configuration.Config] = None,
        schemafile: Optional[str] = None,
        schema: Optional[Dict] = None,
        irc_logging: bool = True,
    ) -> None:
        """Initialize conftool."""
        if configfile is not None:
            self.configuration = configuration.get(configfile)
        elif config is not None:
            self.configuration = config
        else:
            raise ValueError(
                "Either a configfile or a configuration must be passed to ConftoolClient()"
            )
        KVObject.setup(self.configuration)
        if schema is not None:
            self.schema = Schema.from_data(schema)
        elif schemafile is not None:
            self.schema = Schema.from_file(schemafile)
        else:
            raise ValueError(
                "Either a configfile or a configuration must be passed to ConftoolClient()"
            )
        if irc_logging:
            setup_irc(self.configuration)

    def get(self, entity_name: str) -> Entity:
        """Returns the requested conftool object type client.

        Raises:
        """
        try:
            return self.schema.entities[entity_name]
        except KeyError as exc:
            raise ObjectTypeError(entity_name) from exc
