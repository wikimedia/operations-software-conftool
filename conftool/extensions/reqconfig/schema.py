from typing import Dict

from conftool import configuration
from conftool.cli import ConftoolClient
from conftool.kvobject import Entity
from conftool.loader import Schema

from .error import RequestctlError

# requestctl has its own schema and we don't want to have to configure it.
empty_string = {"type": "string", "default": ""}
empty_list = {"type": "list", "default": []}
empty_cidr_list = {"type": "cidr_list", "default": []}
bool_false = {"type": "bool", "default": False}
SCHEMA: Dict = {
    "ipblock": {
        "path": "request-ipblocks",
        "tags": ["scope"],
        "schema": {
            "cidrs": empty_cidr_list,
            "comment": empty_string,
        },
    },
    "pattern": {
        "path": "request-patterns",
        "tags": ["scope"],
        "schema": {
            "method": empty_string,
            "request_body": empty_string,
            "url_path": empty_string,
            "header": empty_string,
            "header_value": empty_string,
            "query_parameter": empty_string,
            "query_parameter_value": empty_string,
        },
    },
    "action": {
        "path": "request-actions",
        "tags": ["cluster"],
        "schema": {
            "enabled": bool_false,
            "cache_miss_only": {"type": "bool", "default": True},
            "comment": empty_string,
            "expression": empty_string,
            "resp_status": {"type": "int", "default": 429},
            "resp_reason": empty_string,
            "sites": empty_list,
            "do_throttle": bool_false,
            "throttle_requests": {"type": "int", "default": 500},
            "throttle_interval": {"type": "int", "default": 30},
            "throttle_duration": {"type": "int", "default": 1000},
            "throttle_per_ip": bool_false,
            "log_matching": bool_false,
        },
    },
    "vcl": {
        "path": "request-vcl",
        "tags": ["cluster"],
        "schema": {
            "vcl": empty_string,
        },
    },
}
SYNC_ENTITIES = sorted(set(SCHEMA.keys()) - {"vcl"})


def get_schema(conf: configuration.Config) -> Schema:
    """Get the schema for requestctl."""
    return ConftoolClient(config=conf, schema=SCHEMA).schema


def get_obj_from_slug(entity, slug: str) -> Entity:
    """Get an object given a string slug."""
    try:
        tag, name = slug.split("/")
    except ValueError as e:
        raise RequestctlError(f"{slug} doesn't contain a path separator") from e
    return entity(tag, name)
