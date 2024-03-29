import json
import ipaddress
import logging
import os
import re

import jsonschema


_log = logging.getLogger(__name__)


def choice(arg):
    args = arg.split("|")

    def is_in(x):
        if x not in args:
            raise ValueError("{} not in '{}'".format(x, " | ".join(args)))
        return x

    return is_in


def bool_validator(data):
    if not type(data) is bool:
        raise ValueError("Only boolean values are accepted.")
    return data


def dict_validator(data):
    if not isinstance(data, dict):
        raise ValueError("Field must be a dict")
    return data


def cidr_list_validator(data):
    """Validate we have a list of ip addresses"""
    if not isinstance(data, list):
        raise ValueError("values need to be a list")
    clean_data = []
    for element in data:
        try:
            # use strict false to ensure we can accept simple errors like 192.168.1.1/24
            # which would get converted to 192.168.1.0/24
            ipaddress.ip_network(element, strict=False)
            clean_data.append(element)
        except ValueError:
            _log.warning("cidr_list reject invalid network: %s", element)
    return clean_data


def any_validator(data):
    """Any value that can be translated to json is ok."""
    try:
        json.dumps(data)
        return data
    except TypeError:
        raise ValueError("values need to be json-serializable")


validators = {
    "int": int,
    "list": lambda x: x if isinstance(x, list) else [],
    "string": str,
    "bool": bool_validator,
    "enum": choice,
    "dict": dict_validator,
    "cidr_list": cidr_list_validator,
    "any": any_validator,
}


class Validator:
    """Validator container"""

    def __init__(self, expected_type, callback):
        """This object incapsulates the expected type it is callable"""
        self.expected_type = expected_type
        self.callback = callback

    def __call__(self, arg):
        return self.callback(arg)

    def __eq__(self, other):
        return self.expected_type == other.expected_type


def get_validator(validation_string):
    """Get the validator of choice"""
    if validation_string.startswith("enum:"):
        validator, arg = validation_string.split(":", 1)
        callback = validators[validator](arg)
    else:
        validator = validation_string
        callback = validators[validation_string]
    return Validator(validator, callback)


class SchemaRule:
    def __init__(self, name, selector, schemaname):
        self.name = name
        self.selectors = {}
        for tag in selector.split(","):
            k, expr = tag.split("=", 1)
            # All our selector are anchored regexes
            self.selectors[k] = "^{}$".format(expr)
        self.path = schemaname
        # This will be lazy-loaded if the rule gets ever invoked
        self._schema = None

    @property
    def schema(self):
        if self._schema is None:
            with open(self.path, "r") as fh:
                self._schema = json.load(fh)
        return self._schema

    def match(self, tags, name):
        """
        Match the rule against the provided taglist, which should include all tags
        and the name of the object.
        """
        match = True
        for tag, value in tags.items():
            if tag not in self.selectors:
                # if the tag is not in the selector, assume it's ok
                continue
            if not re.search(self.selectors[tag], value):
                match = False
                break
        if match and "name" in self.selectors:
            match = re.search(self.selectors["name"], name) is not None

        return match

    def validate(self, entity_data):
        try:
            jsonschema.validate(entity_data, self.schema)
            return True
        except jsonschema.exceptions.ValidationError as exc:
            raise ValueError(exc.message)


class JsonSchemaLoader:
    def __init__(self, base_path="schemas", rules=None):
        self.base_path = base_path
        self.rules = []  # rules stack
        if rules is None:
            return
        for name, schema_def in rules.items():
            path = os.path.join(self.base_path, schema_def["schema"])
            rule = SchemaRule(name, schema_def["selector"], path)
            self.rules.append(rule)

    def rules_for(self, tags, name):
        return [rule for rule in self.rules if rule.match(tags, name)]


def get_json_schema(schema_defs):
    return JsonSchemaLoader(**schema_defs)
