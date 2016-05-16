# Conftool cli module
#
import argparse
from collections import defaultdict
import logging
import json
import os
import re
import sys

import yaml

from conftool import _log, action, configuration, loader, setup_irc
from conftool.kvobject import KVObject
from conftool.drivers import BackendError


class ObjectTypeError(Exception):
    """
    Exception raised whenever an inexistent object type is raised
    """
    pass


class ToolCli(object):

    def __init__(self, args):
        self.args = args
        self._load_schema()
        self._tags = self.args.taglist.split(',')
        self.irc = logging.getLogger('conftool.announce')

    def _load_schema(self):
        self._schema = loader.Schema.from_file(self.args.schema)
        try:
            self.entity = self._schema.entities[self.args.object_type]
        except KeyError:
            _log.critical(
                "Object type %s is not available in the current schema",
                self.args.object_type
            )
            raise ObjectTypeError(self.args.object_type)

    def setup(self):
        c = configuration.get(self.args.config)
        KVObject.setup(c)
        setup_irc(c)

    @property
    def tags(self):
        try:
            return self.entity.parse_tags(self._tags)
        except KeyError as e:
            _log.critical(
                "Invalid tag list %s - we're missing tag: %s",
                self.args.taglist, e)
            sys.exit(1)
        except ValueError:
            _log.critical("Invalid tag list %s", self.args.taglist)
            sys.exit(1)

    def host_list(self):
        for objname in self._tagged_host_list():
            arguments = list(self.tags)
            arguments.append(objname)
            yield self.entity(*arguments)

    def _tagged_host_list(self):
        cur_dir = self.entity.dir(*self.tags)
        warn = False
        if self._namedef == "all":
            all_objects = KVObject.backend.driver.ls(cur_dir)
            objlist = [k for (k, v) in all_objects]
            if self._action == "get":
                if self.args.yaml:
                    print yaml.dump(dict(all_objects), default_flow_style=False)
                else:
                    print json.dumps(dict(all_objects))
                return []
            else:
                retval = objlist
                warn = True
        elif not self._namedef.startswith('re:'):
            return [self._namedef]
        else:
            regex = self._namedef.replace('re:', '', 1)
            try:
                r = re.compile(regex)
            except:
                _log.critical("Invalid regexp: %s", regex)
                sys.exit(1)
            objlist = [k for (k, v) in KVObject.backend.driver.ls(cur_dir)]
            retval = [objname for objname in objlist if r.match(objname)]
            warn = (len(objlist) <= 2 * len(retval))
        if warn and self._action[0:3] in ['set', 'del']:
            ToolCli.raise_warning()
        return retval

    def announce(self):
        if self._action != 'get' and not self.args.quiet:
            self.irc.warn(
                "conftool action : %s; selector: %s (tags: %s)", self._action,
                self._namedef, self._tags
            )

    def run_action(self, unit):
        self._action, self._namedef = unit
        return self._run_action()

    def _run_action(self):
        fail = False
        for obj in self.host_list():
            try:
                a = action.Action(obj, self._action)
                msg = a.run()
            except action.ActionError as e:
                fail = True
                _log.error("Invalid action, reason: %s", str(e))
            except BackendError as e:
                fail = True
                _log.error("Error when trying to %s on %s", self._action,
                           self._namedef)
                _log.error("Failure writing to the kvstore: %s", str(e))
            except Exception as e:
                fail = True
                _log.error("Error when trying to %s on %s", self._action,
                           self._namedef)
                _log.exception("Generic action failure: %s", str(e))
            else:
                print(msg)
        if not fail:
            self.announce()
            return True
        else:
            return False

    @staticmethod
    def raise_warning():
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            print "Destructive operations are not scriptable"
            " and should be run from the command line"
            sys.exit(1)

        print "You are operating on more than half of the objects, this is "
        "potentially VERY DANGEROUS: do you want to continue?"
        print "If so, please type: 'Yes, I am sure of what I am doing.'"
        a = raw_input("confctl>")
        if a == "Yes, I am sure of what I am doing.":
            return True
        print "Aborting"
        sys.exit(1)


class ToolCliFind(ToolCli):
    """Subclass used for the --find mode"""
    def __init__(self, args):
        self.args = args
        self._load_schema()
        self.irc = logging.getLogger('conftool.announce')

    @property
    def tags(self):
        return []

    def host_list(self):
        for o in self.entity.find(self._namedef):
            yield o

    def announce(self):
        if self._action != 'get' and not self.args.quiet:
            self.irc.warn(
                "conftool action : %s; selector: %s", self._action,
                self._namedef
            )


class ToolCliByLabel(ToolCliFind):
    """Subclass used for the select mode"""
    def __init__(self, args):
        super(ToolCliByLabel, self).__init__(args)
        self.selectors = {}
        self.parse_selectors()

    def parse_selectors(self):
        for tag in self.args.selector.split(','):
            k, expr = tag.split('=', 1)
            # All our selector are anchored regexes
            self.selectors[k] = re.compile('^%s$' % expr)

    def host_list(self):
        """Gets all the hosts matching our selectors"""
        objects = [obj for obj in self.entity.query(self.selectors)]
        # Any selector that includes multiple objects will show a list of
        # host that have been selected
        if self._action != 'get' and len(objects) > 1:
            self.raise_warning(objects)
        return objects

    def run_action(self, unit):
        self._action = unit
        self._namedef = self.args.selector
        return self._run_action()

    def raise_warning(self, objects):
        tag_hosts = defaultdict(list)
        hosts_set = set()
        for obj in objects:
            path = os.path.dirname(obj.key).replace(self.entity.base_path(), '')
            tag_hosts[path].append(obj.name)
            hosts_set.add(obj.name)

        if self.args.host and len(hosts_set) <= 1:
            # The host option is set and all objects belong to the same host
            return

        print "The selector you chose has selected the following objects:"
        if self.args.yaml:
            print yaml.dump(tag_hosts, default_flow_style=False)
        else:
            print json.dumps(tag_hosts)
        print "Ok to continue? [y/N]"
        a = raw_input("confctl>")
        if a.lower() != 'y':
            print "Aborting"
            sys.exit(1)


def parse_args(cmdline):
    parser = argparse.ArgumentParser(
        description="Tool to interact with the WMF config store",
        epilog="More details at"
        " <https://wikitech.wikimedia.org/wiki/conftool>.",
        fromfile_prefix_chars='@')
    parser.add_argument('--config', help="Config file", default="/etc/conftool/config.yaml")
    parser.add_argument('--object-type', dest="object_type", default='node')
    parser.add_argument('--yaml', action="store_true",
                        default=False, help="output values in YAML")
    parser.add_argument('--host', action='store_true',
                        help='Do not raise warning if all objects belong to the same host')
    parser.add_argument('--debug', action="store_true",
                        default=False, help="print debug info")
    parser.add_argument('--quiet', action="store_true", dest='quiet',
                        default=False, help="Do not announce the change to IRC")
    parser.add_argument(
        '--schema', default="/etc/conftool/schema.yaml",
        help="Schema file that defines additional object types"
    )

    # Subparsers for the three operating models
    subparsers = parser.add_subparsers(
        help='Program mode: tags, find or select', dest='mode')

    # Tags mode
    tags = subparsers.add_parser(
        'tags',
        help="Select a specific service via full list of tags")
    tags.add_argument(
        'taglist',
        help="List of comma-separated tags; they need to "
        "match the base tags of the object type you chose.")

    find = subparsers.add_parser('find',
                                 help="Find all instances of the node by name")
    for subparser in [tags, find]:
        subparser.add_argument('--action', action="append", metavar="ACTIONS",
                               help="the action to take: "
                               " [set/k1=v1:k2=v2...|get|delete]"
                               " node|all|re:<regex>|find:node", nargs=2)
    select = subparsers.add_parser('select',
                                   help="Select nodes via tag selectors")
    select.add_argument(
        'selector',
        help="Label selector in the form tag=regex: "
        "dc=eqiad,cluster=cache_.*,service=nginx,name=.*.eqiad.wmnet")
    select.add_argument('action', action="append", metavar="ACTIONS",
                        help="the action to take: "
                        " [set/k1=v1:k2=v2...|get|delete]")

    return parser.parse_args(cmdline)


def mangle_argv(cmdline):
    """Basic mangling of the command line arguments"""
    # Backwards compatibility. Ugly but passable
    for i, arg in enumerate(cmdline):
        if arg in ['--tags', '--find']:
            cmdline[i] = arg.replace('--', '')
    return cmdline


def main(cmdline=None):
    if cmdline is None:
        cmdline = sys.argv[1:]

    cmdline = mangle_argv(cmdline)
    args = parse_args(cmdline)

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARN)

    try:

        if args.mode == 'select':
            cli = ToolCliByLabel(args)
        elif args.mode == 'find':
            cli = ToolCliFind(args)
        else:
            cli = ToolCli(args)
    except ObjectTypeError:
        sys.exit(1)

    try:
        cli.setup()
    except Exception as e:
        _log.critical("Invalid configuration: %s", e)
        sys.exit(1)

    exit_status = 0
    for unit in args.action:
        # TODO: fix base class
        if not cli.run_action(unit):
            exit_status = 1
    sys.exit(exit_status)


if __name__ == '__main__':
    main()
