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
from typing import Any, Dict, Generator, List, Optional, Tuple

import pyparsing as pp
import yaml
from wmflib.interactive import AbortError, ask_confirmation

from conftool import IRCSocketHandler, configuration, yaml_safe_load
from conftool.drivers import BackendError
from conftool.extensions.reqconfig.translate import VCLTranslator, VSLTranslator
from conftool.kvobject import Entity

from . import view
from .schema import SCHEMA, get_schema, get_obj_from_slug, SYNC_ENTITIES
from .error import RequestctlError

irc = logging.getLogger("reqctl.announce")
logger = logging.getLogger("reqctl")
config = configuration.Config()


class Requestctl:
    """Cli tool to interact with the dynamic banning of urls."""

    ACTION_ONLY_CMD = ["enable", "disable", "commit", "vcl", "log", "find"]

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
        if (self.config.tcpircbot_host and self.config.tcpircbot_port) and not irc.handlers:
            irc.addHandler(IRCSocketHandler(config.tcpircbot_host, config.tcpircbot_port))
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
        # Load the parsing grammar. If the command is validate, use on-disk check of existence for
        # patterns.
        # Otherwise, check on the datastore.
        if self.args.command == "validate":
            self._obj_exist = self._is_obj_on_fs
        else:
            self._obj_exist = self._is_obj_on_backend
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

    def validate(self):
        """Scans a directory, checks validity of the objects.

        Raises an exception if invalid objects have been found.
        """
        # The code is quite similar to the one in sync; however abstracting it
        # gets ugly fast. I chose code readability over DRY here consciously.
        root_path = pathlib.Path(self.args.basedir)
        failed = False
        for obj_type in SYNC_ENTITIES:
            self.cls = self.schema.entities[obj_type]
            for tag, fpath in self._get_files_for_object_type(root_path, obj_type):
                obj, from_disk = self._entity_from_file(tag, fpath)
                try:
                    self._verify_change(from_disk, obj_type)
                except RequestctlError as e:
                    failed = True
                    logger.error("%s %s is invalid: %s", obj_type, obj.pprint(), e)
                    continue
        if failed:
            raise RequestctlError("Validation failed, see above.")

    def sync(self):
        """Synchronizes entries for an entity from files on disk."""
        # Let's keep things simple, we only have one layer of tags
        # for request objects.
        failed = False
        for tag, fpath in self._get_files_for_object_type(pathlib.Path(self.args.git_repo)):
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
                a for a in self.schema.entities["action"].query({"name": re.compile(".*")})
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

    def find(self):
        """Find actions that correspond to the searched pattern."""
        pattern = f"pattern@{self.args.search_string}"
        ipblock = f"ipblock@{self.args.search_string}"
        matches = 0
        for action in self._get():
            tokens = self._parse_and_check(action.expression)
            if pattern in tokens or ipblock in tokens:
                matches += 1
                print(f"action: {action.pprint()}, expression: {action.expression}")
        if not matches:
            print("No entries found.")

    def vcl(self):
        """Print out the VCL for a specific action."""
        objs = self._get(must_exist=True)
        objs[0].vcl_expression = self._vcl_from_expression(objs[0].expression)
        print(view.get("vcl").render(objs, "vcl"))

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
            if not any([action.enabled, action.log_matching]):
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
                vcl_content = view.get("vcl").render(actions, "commit")
                obj = vcl(cluster, name)
                if not batch:
                    if obj.exists:
                        prev_vcl = obj.vcl
                    else:
                        prev_vcl = ""
                    if not self._confirm_diff(prev_vcl, vcl_content, obj.pprint()):
                        continue
                obj.vcl = vcl_content
                obj.write()
        # Now clean up things that are leftover
        for rules in vcl.query({"name": re.compile(".*")}):
            cluster = rules.tags["cluster"]
            if rules.name not in actions_by_tag_site[cluster]:
                if not batch and not self._confirm_diff(rules.vcl, "", obj.pprint()):
                    continue

                obj.vcl = vcl_content
                obj.write()
                rules.update({"vcl": ""})

    # End public interface
    def _get_files_for_object_type(
        self, root_path: pathlib.Path, obj_type: Optional[str] = None
    ) -> Generator[Tuple[str, pathlib.Path], None, None]:
        """Gets files in a directory that can contain objects."""
        if obj_type is None:
            obj_type = self.object_type
        entity_path: pathlib.Path = root_path / self.schema.entities[obj_type].base_path()
        for tag_path in entity_path.iterdir():
            # skip files in the root dir, including any hidden dirs and the special
            # .. and . references
            if not tag_path.is_dir() or tag_path.parts[-1].startswith("."):
                continue
            tag = tag_path.name
            for fpath in tag_path.glob("*.yaml"):
                yield (tag, fpath)

    def _confirm_diff(self, old: str, new: str, slug: str) -> bool:
        """Confirm if a change needs to be carried on or not."""
        diff = self._vcl_diff(old, new, slug)
        if not diff:
            return False
        print(diff)
        try:
            ask_confirmation("Ok to commit these changes?")
        except AbortError:
            return False
        return True

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
                raise RequestctlError(f"{self.object_type} {obj.pprint()} not found.")
        else:
            objs = list(self.cls.query({"name": re.compile(".")}))
        return objs

    def _enable(self, enable: bool):
        """Ban a type of request."""
        action = get_obj_from_slug(self.schema.entities["action"], self.args.action)
        if not action.exists:
            raise RequestctlError(f"{self.args.action} does not exist, cannot enable.")
        action.update({"enabled": enable})
        # Printing this unconditionally *might* be confusing, as there's nothing to commit if
        # enabling an already-enabled action. So we could check first, with action.changed(), but it
        # probably isn't worth the extra roundtrip.
        print("Remember to commit the change to VCL with: sudo requestctl commit")

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
        <boolean> ::= "AND" | "OR" | "AND NOT" | "OR NOT"

        """
        boolean = (
            pp.Keyword("AND NOT") | pp.Keyword("OR NOT") | pp.Keyword("AND") | pp.Keyword("OR")
        )
        lpar = pp.Literal("(")
        rpar = pp.Literal(")")
        element = pp.Word(pp.alphanums + "/-_")
        pattern = pp.Combine("pattern@" + element.setParseAction(self._validate_pattern))
        ipblock = pp.Combine("ipblock@" + element.setParseAction(self._validate_ipblock))
        grm = pp.Forward()
        item = pattern | ipblock | lpar + grm + rpar
        grm << pp.Group(item) + pp.ZeroOrMore(pp.Group(boolean + item))
        return grm

    def _validate_pattern(self, _all, _pos, tokens):
        """Ensure a pattern referenced exists."""
        for pattern in tokens:
            if not self._obj_exist("pattern", pattern):
                msg = f"The pattern {pattern} is not present on the backend."
                logger.error(msg)
                # also raise an exception to make parsing fail.
                raise pp.ParseException(msg)

    def _validate_ipblock(self, _all, _pos, tokens):
        """Ensure an ipblock referenced exists."""
        for ipblock in tokens:
            if not self._obj_exist("ipblock", ipblock):
                msg = f"The ipblock {ipblock} is not present on the backend."
                logger.error(msg)
                raise pp.ParseException(msg)

    def _is_obj_on_backend(self, obj_type: str, slug: str) -> bool:
        """Checks if the pattern exists on the backend."""
        obj = get_obj_from_slug(self.schema.entities[obj_type], slug)
        return obj.exists

    def _is_obj_on_fs(self, obj_type: str, slug: str) -> bool:
        on_disk: pathlib.Path = (
            pathlib.Path(self.args.basedir)
            / self.schema.entities[obj_type].base_path()
            / f"{slug}.yaml"
        )
        return on_disk.is_file()

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

    def _entity_from_file(self, tag: str, file_path: pathlib.Path) -> Tuple[Entity, Optional[Dict]]:
        """Get an entity from a file path, and the corresponding data to update."""
        from_disk = yaml_safe_load(file_path, {})
        entity_name = file_path.stem
        entity = self.cls(tag, entity_name)
        return (entity, from_disk)

    def _verify_change(self, changes: Dict[str, Any], object_type: Optional[str] = None) -> Dict:
        """
        Verifies a change is ok. Eitehr Raises an exception
        or returns the valid changes.
        """
        if object_type is None:
            object_type = self.object_type
        if object_type == "pattern":
            if changes.get("body", False) and changes.get("method", "") != "POST":
                raise RequestctlError("Cannot add a request body in a request other than POST.")
        if object_type != "action":
            return changes
        try:
            changes["expression"] = " ".join(self._parse_and_check(changes["expression"]))
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
        parsed = self._parse_and_check(expression)
        vsl = VSLTranslator(self.schema)
        return vsl.from_expression(parsed)

    def _vcl_from_expression(self, expression: str) -> str:
        parsed = self._parse_and_check(expression)
        vcl = VCLTranslator(self.schema)
        return vcl.from_expression(parsed)
