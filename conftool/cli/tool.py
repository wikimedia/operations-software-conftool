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

object_types = {"node": node.Node, "service": service.Service}


def host_list(name, cur_dir, act):
    warn = False
    if name == "all":
        all = KVObject.backend.driver.ls(cur_dir)
        objlist = [k for (k,v) in all]
        if act == "get":
            print json.dumps(dict(all))
            return []
        else:
            retval = objlist
            warn = True
    elif not name.startswith('re:'):
        return [name]
    else:
        regex = name.replace('re:', '', 1)
        try:
            r = re.compile(regex)
        except:
            _log.critical("Invalid regexp: %s", regex)
            sys.exit(1)
        objlist = [k for (k,v) in KVObject.backend.driver.ls(cur_dir)]
        retval = [objname for objname in objlist if r.match(objname)]
        warn = (len(objlist) <= 2 * len(retval))
    if warn and act in ['set', 'del']:
        raise_warning()
    return retval

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
                        required=True)
    parser.add_argument('--object-type', dest="object_type",
                        choices=object_types.keys(), default='node')
    parser.add_argument('--action', action="append", metavar="ACTIONS",
                        help="the action to take: "
                        " [set/k1=v1:k2=v2...|get|delete]"
                        " node|all|re:<regex>", nargs=2,
                        required=True)
    parser.add_argument('--debug', action="store_true",
                        default=False, help="print debug info")
    args = parser.parse_args(cmdline)

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARN)

    try:
        c = configuration.get(args.config)
        KVObject.setup(c)
    except Exception as e:
        _log.critical("Invalid configuration: %s", e)
        sys.exit(1)

    cls = object_types[args.object_type]
    try:
        tags = cls.get_tags(args.tags.split(','))
    except KeyError as e:
        _log.critical(
            "Invalid tag list %s - we're missing tag: %s", args.tags, e)
        sys.exit(1)

    for unit in args.action:
        act, n = unit
        cur_dir = cls.dir(*tags)
        for name in host_list(n, cur_dir, act):
            try:
                # Oh python I <3 you...
                arguments = list(tags)
                arguments.append(name)
                obj = cls(*arguments)
                a = action.Action(obj, act)
                msg = a.run()
            except action.ActionError as e:
                _log.error("Invalid action, reason: %s", str(e))
            except BackendError as e:
                _log.error("Failure writing to the kvstore: %s", str(e))
            except Exception as e:
                _log.error("Generic action failure: %s", str(e))
            else:
                print(msg)


if __name__ == '__main__':
    main()
