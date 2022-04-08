"""
This is the cli interface for the reqconfig extension.
Given the interface is very different from the other *ctl commands,
We don't necessarily derive it from the base cli tools.
"""

import argparse
import difflib
import logging
import pathlib
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import pyparsing as pp
import yaml
from wmflib.interactive import AbortError, ask_confirmation

from conftool import IRCSocketHandler, configuration, yaml_safe_load
from conftool.drivers import BackendError
from conftool.kvobject import Entity, KVObject
from conftool.loader import Schema

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
    "vcl": {
        "path": "request-vcl",
        "tags": ["cluster"],
        "schema": {
            "vcl": empty_string,
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

    ACTION_ONLY_CMD = ["enable", "disable", "commit", "vcl", "log"]

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
        if self.args.command in self.ACTION_ONLY_CMD:
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
                changes = self._object_diff(obj, to_load)
                if changes:
                    try:
                        self._write(obj, to_load)
                    except BackendError as e:
                        logger.error(
                            "Error writing to etcd for %s: %s", obj.pprint(), e
                        )
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
        else:
            all_actions = []
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
        self._pprint(self._get())

    def log(self):
        """Print out the varnishlog command corresponding to the selected action."""
        objs = self._get(must_exist=True)
        objs[0].vsl_expression = self._vsl_from_expression(objs[0].expression)
        print(view.get("vsl").render(objs, "action"))

    def vcl(self):
        """Print out the VCL for a specific action."""
        objs = self._get(must_exist=True)
        objs[0].vcl_expression = self._vcl_from_expression(objs[0].expression)
        print(view.get("vcl").render(objs, "action"))

    def commit(self):
        """Commit the enabled actions to vcl, asking confirmation with a diff."""
        # First we need to build the vcl groups:
        # - one cache-$cluster/global key with all vcl rules that go to all sites
        # - one cache-$cluster/$dc key for every datacenter named in "sites" of any
        #   action
        batch = self.args.batch
        vcl = self.schema.entities["vcl"]
        actions_by_tag_site = defaultdict(lambda: defaultdict(list))
        for action in self._get():
            if not action.enabled:
                continue
            action.vcl_expression = self._vcl_from_expression(action.expression)
            cluster = action.tags["cluster"]
            if not action.sites:

                actions_by_tag_site[cluster]["global"].append(action)
            else:
                for site in action.sites:
                    actions_by_tag_site[cluster][site].append(action)
        for cluster, entries in actions_by_tag_site.items():
            for name, actions in entries.items():
                vcl_content = view.get("vcl").render(actions, "action")
                obj = vcl(cluster, name)
                if not batch:
                    if obj.exists:
                        prev_vcl = obj.vcl
                    else:
                        prev_vcl = ""
                    print(
                        self._vcl_diff(
                            prev_vcl,
                            vcl_content,
                            obj.pprint(),
                        )
                    )
                    try:
                        ask_confirmation("Ok to commit these changes?")
                    except AbortError:
                        continue
                obj.vcl = vcl_content
                obj.write()
        # Now clean up things that are leftover
        for rules in vcl.query({"name": re.compile(".*")}):
            cluster = rules.tags["cluster"]
            if rules.name not in actions_by_tag_site[cluster]:
                if not batch:
                    print(self._vcl_diff(rules.vcl, "", obj.pprint()))
                    try:
                        ask_confirmation("Ok to commit these changes?")
                    except AbortError:
                        continue
                obj.vcl = vcl_content
                obj.write()
                rules.update({"vcl": ""})

    # End public interface
    def _vcl_diff(self, old: str, new: str, slug: str) -> str:
        """Diffs between two pieces of VCL."""
        if old == "":
            fromfile = "null"
        else:
            fromfile = f"{slug}.old"
        if new == "":
            tofile = "null"
        else:
            tofile = f"{slug}.new"
        return "".join(
            [
                line + "\n"
                for line in difflib.unified_diff(
                    old.splitlines(), new.splitlines(), fromfile=fromfile, tofile=tofile
                )
            ]
        )

    def _get(self, must_exist: bool = False):
        """Get an object, or all of them, return them as a list."""
        if "object_path" in self.args and self.args.object_path:
            objs = []
            obj = get_obj_from_slug(self.cls, self.args.object_path)
            if obj.exists:
                objs.append(obj)
            elif must_exist:
                raise RequestctlError("{self.object_type} {obj.pprint()} not found.")
        else:
            objs = list(self.cls.query({"name": re.compile(".")}))
        return objs

    def _enable(self, enable: bool):
        """Ban a type of request."""
        action = get_obj_from_slug(self.schema.entities["action"], self.args.action)
        if not action.exists:
            raise RequestctlError(f"{self.args.action} does not exist, cannot enable.")
        action.update({"enabled": enable})

    def _parse_and_check(self, expression) -> List[str]:
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

        return flatten(parsed.asList())

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
                msg = f"The pattern {pattern} is not present on the backend."
                logger.error(msg)
                # also raise an exception to make parsing fail.
                raise pp.ParseException(msg)

    def _validate_ipblock(self, _all, _pos, tokens):
        """Ensure an ipblock referenced exists."""
        for ipblock in tokens:
            obj = get_obj_from_slug(self.schema.entities["ipblock"], ipblock)
            if not obj.exists:
                msg = f"The ipblock {ipblock} is not present on the backend."
                logger.error(msg)
                raise pp.ParseException(msg)

    def _pprint(self, entities: List[Entity]):
        """Pretty print the results."""
        # VCL and VSL output modes are only supported for "action"
        # Also, pretty mode is disabled for all but patterns and ipblocks.
        # Actions should be supported, but is temporarily disabled
        #  while we iron out the issues with old versions of tabulate
        output_config = {
            "action": {"allowed": ["vsl", "vcl", "yaml", "json"], "default": "yaml"},
            "vcl": {"allowed": ["yaml", "json"], "default": "json"},
        }
        out = self.args.output
        if self.object_type in output_config:
            conf = output_config[self.object_type]
            if out not in conf["allowed"]:
                out = conf["default"]
        print(view.get(out).render(entities, self.object_type))

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
        if self.object_type == "pattern":
            if changes.get("body", False) and changes.get("method", "") != "POST":
                raise RequestctlError(
                    "Cannot add a request body in a request other than POST."
                )
        if self.object_type != "action":
            return changes
        try:
            changes["expression"] = " ".join(
                self._parse_and_check(changes["expression"])
            )
        except pp.ParseException as e:
            raise RequestctlError(e) from e
        try:
            # We never sync the enabled state from disk.
            del changes["enabled"]
        except KeyError:
            pass
        return changes

    def _object_diff(self, entity: Entity, to_load: Dict[str, Any]) -> Dict:
        """Asks for confirmation of changes if needed."""
        if entity.exists:
            changes = entity.changed(to_load)
            action = "modify"
            msg = f"{self.object_type.capitalize()} {entity.pprint()} will be changed:"
        else:
            action = "create"
            changes = to_load
            msg = f"{self.object_type.capitalize()} will be created:"

        if self.args.interactive and changes:
            print(msg)
            for key, value in changes.items():
                print(f"{entity.name}.{key}: '{getattr(entity, key)}' => {value}")
            try:
                ask_confirmation(f"Do you want to {action} this object?")
            except AbortError:
                # act like there were no changes
                return {}
        return changes

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

    def _vsl_from_expression(self, expression: str) -> str:
        """Obtain the vsl query from the expression"""
        query = []
        parsed = self._parse_and_check(expression)
        for token in parsed:
            if token in ["(", ")", "AND", "OR"]:
                query.append(token.lower())
            elif token.startswith("ipblock@"):
                what, name = token.split("/")
                if what == "ipblock@cloud":
                    query.append(f'ReqHeader:X-Public-Cloud ~ "{name}"')
                elif what == "ipblock@abuse":
                    query.append(f'VCL_acl ~ "^MATCH {name}"')
            elif token.startswith("pattern@"):
                slug = token.replace("pattern@", "")
                obj = get_obj_from_slug(self.schema.entities["pattern"], slug)
                if obj.method:
                    query.append(f'ReqMethod ~ "{obj.method}"')
                if obj.header:
                    if obj.header_value != "":
                        query.append(f'ReqHeader:{obj.header} ~ "{obj.header_value}"')
                    else:
                        query.append(f"not ReqHeader:{obj.header}")
                if obj.url_path:
                    if obj.query_parameter:
                        qs = f"[?&]{obj.query_parameter}={obj.query_parameter_value}"
                        query.append(f'ReqURL ~ "{obj.url_path}.*{qs}"')
                    else:
                        query.append(f'ReqURL ~ "{obj.url_path}"')
                # We need to use else if because we don't want to act if uri_path was defined.
                elif obj.query_parameter:
                    query.append(
                        f'ReqURL ~ "[?&]{obj.query_parameter}={obj.query_parameter_value}"'
                    )
        return " ".join(query)

    def _vcl_from_expression(self, expression: str) -> str:
        translations = {"(": "(", ")": ")", "AND": " && ", "OR": " || "}
        vcl_expression = ""
        parsed = self._parse_and_check(expression)
        for token in parsed:
            if token in translations:
                vcl_expression += translations[token]
            elif token.startswith("pattern@"):
                slug = token.replace("pattern@", "")
                vcl_expression += self._vcl_from_pattern(slug)
            elif token.startswith("ipblock@"):
                slug = token.replace("ipblock@", "")
                vcl_expression += self._vcl_from_ipblock(slug)
        return vcl_expression

    def _vcl_from_pattern(self, slug: str) -> str:
        out_vcl = []
        obj = get_obj_from_slug(self.schema.entities["pattern"], slug)
        if obj.method:
            out_vcl.append(f'req.method == "{obj.method}"')
        url_rule = vcl_url_match(
            obj.url_path, obj.query_parameter, obj.query_parameter_value
        )
        if url_rule != "":
            out_vcl.append(url_rule)
        if obj.header:
            if obj.header_value:
                out_vcl.append(f'req.http.{obj.header} ~ "{obj.header_value}"')
            # Header with no value means absence of the header
            else:
                out_vcl.append(f"!req.http.{obj.header}")
        # Do not add a request_body filter to anything but POST.
        if obj.request_body and obj.method == "POST":
            out_vcl.append(f'req.body ~ "{obj.request_body}"')
        if len(out_vcl) > 1:
            joined = " && ".join(out_vcl)
            return f"({joined})"
        return out_vcl.pop()

    def _vcl_from_ipblock(self, slug: str) -> str:
        scope, value = slug.split("/")
        if scope == "cloud":
            return f'req.http.X-Public-Cloud ~ "{value}"'
        elif scope == "abuse":
            return f'std.ip(req.http.X-Client-IP, "192.0.2.1") ~ {value}'


def vcl_url_match(url: str, param: str, value: str) -> str:
    """Return the query corresponding to the pattern."""
    if not any([url, param, value]):
        return ""
    out = 'req.url ~ "'
    if url != "":
        out += url
        if param != "":
            out += ".*"
    if param != "":
        out += f"[?&]{param}"
        if value != "":
            out += f"={value}"
    # close the quotes
    out += '"'
    return out
