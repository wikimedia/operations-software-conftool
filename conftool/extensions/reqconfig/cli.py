"""
This is the cli interface for the reqconfig extension.
Given the interface is very different from the other *ctl commands,
We don't necessarily derive it from the base cli tools.
"""

import argparse
import logging
import pathlib
import re
from typing import List, Optional, Tuple, Dict, Any

import pyparsing as pp
import yaml
from conftool import IRCSocketHandler, configuration, yaml_safe_load
from conftool.drivers import BackendError
from conftool.kvobject import Entity, KVObject
from conftool.loader import Schema
from wmflib.interactive import AbortError, ask_confirmation

from . import view

irc = logging.getLogger("reqctl.announce")
logger = logging.getLogger("reqctl")
config = configuration.Config()
# requestctl has its own schema and we don't want to have to configure it.
empty_string = {"type": "string", "default": ""}
empty_list = {"type": "list", "default": []}
bool_false = {"type": "bool", "default": False}
SCHEMA: Dict = {
    "ipblock": {
        "path": "request-ipblocks",
        "tags": ["scope"],
        "schema": {
            "cidrs": empty_list,
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
        },
    },
}


def get_schema(conf: configuration.Config) -> Schema:
    """Get the schema for requestctl."""
    KVObject.setup(conf)
    return Schema.from_data(SCHEMA, default_entities=False)


def get_obj_from_slug(entity, slug: str) -> Entity:
    """Get an object given a string slug."""
    try:
        tag, name = slug.split("/")
    except ValueError as e:
        raise RequestctlError(f"{slug} doesn't contain a path separator") from e
    return entity(tag, name)


class RequestctlError(Exception):
    """Local wrapper class for managed exceptions."""


class Requestctl:
    """Cli tool to interact with the dynamic banning of urls."""

    def __init__(self, args: argparse.Namespace) -> None:
        if args.debug:
            lvl = logging.DEBUG
        else:
            lvl = logging.INFO
        logging.basicConfig(
            level=lvl,
            format="%(asctime)s - %(name)s "
            "(%(module)s:%(funcName)s:%(lineno)d) - %(levelname)s - %(message)s",
        )
        self.args = args
        if self.args.config is not None:
            self.config = configuration.get(self.args.config)
        else:
            self.config = configuration.Config()
        if (
            self.config.tcpircbot_host and self.config.tcpircbot_port
        ) and not irc.handlers:
            irc.addHandler(
                IRCSocketHandler(config.tcpircbot_host, config.tcpircbot_port)
            )
        # Now let's load the schema
        self.schema = get_schema(self.config)
        # Load the right entity
        self.cls = self.schema.entities[self.object_type]
        if "git_repo" in self.args and self.args.git_repo is not None:
            self.base_path: Optional[pathlib.Path] = (
                pathlib.Path(self.args.git_repo) / self.cls.base_path()
            )
        else:
            self.base_path = None
        self.expression_grammar = self.grammar()

    @property
    def object_type(self) -> str:
        """The object type we're operating on."""
        if self.args.command in ["enable", "disable"]:
            return "action"
        return self.args.object_type

    def run(self):
        """Runs the action defined in the cli args."""
        try:
            command = getattr(self, self.args.command)
        except AttributeError as e:
            raise RequestctlError(f"Command {self.args.command} not implemented") from e
        command()

    def sync(self):
        """Synchronizes entries for an entity from files on disk."""
        # Let's keep things simple, we only have one layer of tags
        # for request objects.
        failed = False
        for tag_path in self.base_path.iterdir():
            if not tag_path.is_dir() or tag_path.parts[-1].startswith("."):
                continue
            tag = tag_path.name
            for fpath in tag_path.glob("*.yaml"):
                obj, from_disk = self._entity_from_file(tag, fpath)
                try:
                    to_load = self._verify_change(from_disk)
                except RequestctlError as e:
                    failed = True
                    logger.error("Error parsing %s, skipping: %s", obj.pprint(), e)
                    continue
                if self.args.interactive:
                    try:
                        self._object_diff(obj, to_load)
                    except AbortError:
                        continue
                try:
                    self._write(obj, to_load)
                except BackendError as e:
                    logger.error("Error writing to etcd for %s: %s", obj.pprint(), e)
                    failed = True
                    continue

        # If we're not purging, let's stop here.
        if not self.args.purge:
            if failed:
                raise RequestctlError(
                    "synchronization had issues, please check the output for details."
                )
            return

        # Now let's find any object that is in the datastore and not on disk.
        # Given how query is implemented, it's better to just search for all objects
        # and check everything in one go.
        # Given we also need to check consistency, we need all actions too.

        if self.object_type != "action":
            all_actions = [
                a
                for a in self.schema.entities["action"].query(
                    {"name": re.compile(".*")}
                )
            ]
        for reqobj in self.cls.query({"name": re.compile(".*")}):
            if not self._should_have_path(reqobj).is_file():
                if not self._is_safe_to_remove(reqobj, all_actions):
                    failed = True
                    continue
                if self.args.interactive:
                    try:
                        ask_confirmation(f"Proceed to delete {reqobj}?")
                    except AbortError:
                        continue
                logger.info("Deleting %s", reqobj.name)
                reqobj.delete()

        if failed:
            raise RequestctlError(
                "synchronization had issues, please check the output for details."
            )

    def dump(self):
        """Dump an object type."""
        for reqobj in self.cls.query({"name": re.compile(".*")}):
            object_path = self.base_path / f"{reqobj.pprint()}.yaml"
            object_path.absolute().parent.mkdir(parents=True, exist_ok=True)
            contents = reqobj.asdict()[reqobj.name]
            object_path.write_text(yaml.dump(contents))

    def enable(self):
        """Enable an action."""
        self._enable(True)

    def disable(self):
        """Disable an action."""
        self._enable(False)

    def get(self):
        """Get an object, or an entire class of them, print them out."""
        entity = self.schema.entities[self.object_type]
        if self.args.object_path:
            objs = []
            obj = get_obj_from_slug(entity, self.args.object_path)
            if obj.exists:
                objs.append(obj)
        else:
            objs = list(entity.query({"name": re.compile(".")}))

        self._pprint(objs)

    # End public interface

    def _enable(self, enable: bool):
        """Ban a type of request."""
        action = get_obj_from_slug(self.schema.entities["action"], self.args.action)
        if not action.exists:
            raise RequestctlError(f"{self.args.action} does not exist, cannot enable.")
        action.update({"enabled": enable})

    def _parse_and_check(self, expression):
        """Parse the expression and check if it's valid at all.

        If the expression is not balanced, or has references to inexistent ipblocks or patterns,
        an error will be raised.
        """
        parsed = self.expression_grammar.parseString(expression, parseAll=True)
        # If this didn't raise an exception, the string was valid. Now let's put it in normalized
        # form like it needs to be in etcd

        def flatten(parse):
            res = []
            for el in parse:
                if isinstance(el, list):
                    res.extend(flatten(el))
                else:
                    res.append(el)
            return res

        return " ".join(flatten(parsed.asList()))

    def grammar(self) -> pp.Forward:
        """
        Pyparsing based grammar for expressions in actions.

        BNF of the grammar:
        <grammar> ::= <item> | <item> <boolean> <grammar>
        <item> ::= <pattern> | <ipblock> | "(" <grammar> ")"
        <pattern> ::= "pattern@" <pattern_path>
        <ipblock> ::= "ipblock@"<ipblock_path>
        <boolean> ::= "AND" | "OR"

        """
        boolean = pp.Keyword("AND") | pp.Keyword("OR")
        lpar = pp.Literal("(")
        rpar = pp.Literal(")")
        element = pp.Word(pp.alphanums + "/-_")
        pattern = pp.Combine(
            "pattern@" + element.setParseAction(self._validate_pattern)
        )
        ipblock = pp.Combine(
            "ipblock@" + element.setParseAction(self._validate_ipblock)
        )
        grm = pp.Forward()
        item = pattern | ipblock | lpar + grm + rpar
        grm << pp.Group(item) + pp.ZeroOrMore(pp.Group(boolean + item))
        return grm

    def _validate_pattern(self, _all, _pos, tokens):
        """Ensure a pattern referenced exists."""
        for pattern in tokens:
            obj = get_obj_from_slug(self.schema.entities["pattern"], pattern)
            if not obj.exists:
                raise pp.ParseException(
                    f"The pattern {pattern} is not present on the backend."
                )

    def _validate_ipblock(self, _all, _pos, tokens):
        """Ensure an ipblock referenced exists."""
        for ipblock in tokens:
            obj = get_obj_from_slug(self.schema.entities["ipblock"], ipblock)
            if not obj.exists:
                raise pp.ParseException(
                    f"The ipblock {ipblock} is not present on the backend."
                )

    def _pprint(self, entities: List[Entity]):
        """Pretty print the results."""
        print(view.get(self.args.output).render(entities, self.object_type))

    def _entity_from_file(
        self, tag: str, file_path: pathlib.Path
    ) -> Tuple[Entity, Optional[Dict]]:
        """Get an entity from a file path, and the corresponding data to update."""
        from_disk = yaml_safe_load(file_path, {})
        entity_name = file_path.stem
        entity = self.cls(tag, entity_name)
        return (entity, from_disk)

    def _verify_change(self, changes: Dict[str, Any]) -> Dict:
        """
        Verifies a change is ok. Eitehr Raises an exception
        or returns the valid changes.
        """
        if not self.object_type == "action":
            return changes
        try:
            changes["expression"] = self._parse_and_check(changes["expression"])
            # We never sync the enabled state from disk.
            del changes["enabled"]
            return changes
        except pp.ParseException as e:
            raise RequestctlError(e) from e

    def _object_diff(self, entity: Entity, to_load: Dict[str, Any]):
        """Asks for confirmation of changes if needed."""
        if entity.exists:
            action = "modify"
            changes = entity.changed(to_load)
            print(f"{self.object_type.capitalize()} {entity.pprint()} will be changed:")
        else:
            action = "create"
            changes = to_load
            print(f"{self.object_type.capitalize()} will be created:")
        for key, value in changes.items():
            print(f"{entity.name}.{key}: '{getattr(entity, key)}' => {changes[key]}")
        ask_confirmation(f"Do you want to {action} this object?")

    def _write(self, entity: Entity, to_load: Dict[str, Any]):
        """Write the object to the datastore."""
        if entity.exists:
            logger.info("Updating %s %s", self.object_type, entity.pprint())
            entity.update(to_load)
        else:
            logger.info("Creating %s %s", self.object_type, entity.pprint())
            entity.from_net(to_load)
            entity.write()

    def _should_have_path(self, obj: Entity) -> pathlib.Path:
        """Path expected on disk for a specific entity."""
        tag = SCHEMA[self.object_type]["tags"][0]
        return self.base_path / obj.tags[tag] / f"{obj.name}.yaml"

    def _is_safe_to_remove(self, entity: Entity, actions: List[Entity]) -> bool:
        """Check if a pattern/ipblock is referenced in any action and thus not safe to remove."""
        if self.object_type == "action":
            return True
        expr = f"{self.object_type}@{entity.pprint()}"
        matches = [r.pprint() for r in actions if (expr in r.expression)]
        if matches:
            logger.error(
                "Cannot remove %s %s: still referenced in the following actions: %s",
                self.object_type,
                entity.pprint(),
                ",".join(matches),
            )
            return False
        return True
