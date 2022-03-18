"""Views for requestctl."""
import json
import textwrap
import yaml

import tabulate

from typing import Dict, List
from conftool.kvobject import Entity


def get(fmt: str) -> "View":
    """Factory method to get a view class.

    Typical use: reqconfig.view.get("json").render(data)
    """
    if fmt == "json":
        return JsonView
    elif fmt == "yaml":
        return YamlView
    elif fmt == "pretty":
        return PrettyView
    else:
        raise ValueError(f"Unsupported format '{format}'")


class View:
    """Abstract view interface"""

    @classmethod
    def render(cls, data: List[Entity], object_type: str) -> str:
        """Renders the view."""


class YamlView(View):
    """Yaml representation of our objects."""

    @classmethod
    def dump(cls, data: List[Entity]) -> Dict[str, Dict]:
        """Create a easily-human-readable dump of the data."""
        dump = {}
        for entity in data:
            asdict = entity.asdict()
            dump[entity.pprint()] = asdict[entity.name]
        return dump

    @classmethod
    def render(cls, data: List[Entity], _: str) -> str:
        return yaml.dump(cls.dump(data))


class JsonView(YamlView):
    """Json representation of our objects."""

    @classmethod
    def render(cls, data: List[Entity], _: str) -> str:
        return json.dumps(cls.dump(data))


class PrettyView(View):
    """Pretty-print information about the selected entitites."""

    headers = {
        "pattern": ["name", "pattern"],
        "ipblock": ["name", "cidrs"],
        "action": ["name", "action", "response", "throttle"],
    }

    @classmethod
    def render(cls, data: List[Entity], object_type: str) -> str:
        headers = cls.headers[object_type]
        tabular = []
        for entity in data:
            if object_type == "pattern":
                element = (entity.pprint(), cls.get_pattern(entity))
            elif object_type == "ipblock":
                element = (entity.pprint(), "\n".join(entity.cidrs))
            elif object_type == "action":
                element = (
                    textwrap.shorten(entity.pprint(), width=30),
                    textwrap.fill(entity.expression, width=30),
                    textwrap.shorten(
                        f"{entity.resp_status} {entity.resp_reason}", width=20
                    ),
                    str(entity.do_throttle).lower(),
                )
            tabular.append(element)
        return tabulate.tabulate(tabular, headers, tablefmt="pretty")

    @classmethod
    def get_pattern(cls, entity: Entity) -> str:
        """String representation of a pattern"""
        out = []
        if entity.method:
            out.append(entity.method)
        if entity.url_path:
            out.append(f"url:{entity.url_path}")
        if entity.header:
            out.append(f"{entity.header}: {entity.header_value}")
        if entity.query_parameter:
            out.append(f"?{entity.query_parameter}={entity.query_parameter_value}")
        return "\n".join(out)
