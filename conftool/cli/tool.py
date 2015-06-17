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

object_types = {"node": node.Node, "service": service.Service}

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
                        " [set/k1=v1:k2=v2...|get|delete] node", nargs=2,
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
        _log.critical("Invalid tag list %s - reason: %s", args.tags, e)
        sys.exit(1)

    for unit in args.action:
        try:
            act, name = unit
            if act == 'get' and name == "all":
                cur_dir = cls.dir(*tags)
                print json.dumps(dict(KVObject.backend.driver.ls(cur_dir)))
                return
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
