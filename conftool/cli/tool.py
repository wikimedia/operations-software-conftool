# Conftool cli module
#
import argparse
import sys
import logging
import json
from conftool import configuration, action, _log, KVObject
from conftool.drivers import BackendError
# TODO: auto import these somehow
from conftool import service, node
import re


class ToolCli(object):
    object_types = {"node": node.Node, "service": service.Service}

    def __init__(self, args):
        self.args = args
        if self.args.tags:
            self._tags = self.args.tags.split(',')
        elif not self.args.find:
            _log.critical("Either tags or find should be provided")
            sys.exit(1)
        self.entity = self.object_types[args.object_type]

    def setup(self):
        c = configuration.get(self.args.config)
        KVObject.setup(c)

    @property
    def tags(self):
        if self.args.find:
            return []
        else:
            try:
                return self.entity.get_tags(self._tags)
            except KeyError as e:
                _log.critical(
                    "Invalid tag list %s - we're missing tag: %s",
                    self.args.tags, e)
                sys.exit(1)

    def host_list(self):
        if self.args.find:
            for o in self.entity.find(self._namedef):
                yield o
        else:
            for objname in self._tagged_host_list():
                arguments = list(self.tags)
                arguments.append(objname)
                yield self.entity(*arguments)

    def _tagged_host_list(self):
        cur_dir = self.entity.dir(*self.tags)
        warn = False
        if self._namedef == "all":
            all = KVObject.backend.driver.ls(cur_dir)
            objlist = [k for (k, v) in all]
            if self._action == "get":
                print json.dumps(dict(all))
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

    def run_action(self, act, namedef):
        self._action = act
        self._namedef = namedef
        for obj in self.host_list():
            try:
                a = action.Action(obj, act)
                msg = a.run()
            except action.ActionError as e:
                _log.error("Invalid action, reason: %s", str(e))
            except BackendError as e:
                _log.error("Error when trying to %s on %s", act, namedef)
                _log.error("Failure writing to the kvstore: %s", str(e))
            except Exception as e:
                _log.error("Error when trying to %s on %s", act, namedef)
                _log.error("Generic action failure: %s", str(e))
            else:
                print(msg)

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


def main(cmdline=None):
    if cmdline is None:
        cmdline = list(sys.argv)
        cmdline.pop(0)

    parser = argparse.ArgumentParser(
        description="Tool to interact with the WMF config store",
        epilog="More details at"
        " <https://wikitech.wikimedia.org/wiki/conftool>.",
        fromfile_prefix_chars='@')
    parser.add_argument('--config', help="Optional config file",
                        default="/etc/conftool/config.yaml")
    parser.add_argument('--tags',
                        help="List of comma-separated tags; they need to "
                        "match the base tags of the object type you chose.",
                        required=False, default=[])
    parser.add_argument('--find', help="Find all instances of the node",
                        required=False, default=False, action='store_true')
    parser.add_argument('--object-type', dest="object_type",
                        choices=ToolCli.object_types.keys(), default='node')
    parser.add_argument('--action', action="append", metavar="ACTIONS",
                        help="the action to take: "
                        " [set/k1=v1:k2=v2...|get|delete]"
                        " node|all|re:<regex>|find:node", nargs=2,
                        required=True)
    parser.add_argument('--debug', action="store_true",
                        default=False, help="print debug info")
    args = parser.parse_args(cmdline)

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARN)

    cli = ToolCli(args)

    try:
        cli.setup()
    except Exception as e:
        _log.critical("Invalid configuration: %s", e)
        sys.exit(1)

    for unit in args.action:
        act, name_def = unit
        cli.run_action(act, name_def)


if __name__ == '__main__':
    main()
