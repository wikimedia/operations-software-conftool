"""This extension generates the requestctl tool."""

from argparse import ArgumentParser, Namespace
import logging
import sys


from .cli import Requestctl, RequestctlError, SCHEMA

# public api
from .cli import get_schema  # noqa: F401


def parse_args(args) -> Namespace:
    """Parse command-line arguments."""
    parser = ArgumentParser(
        "requestctl",
        description="Tool to control/ratelimit/ban web requests dynamically",
    )
    parser.add_argument(
        "--config", "-c", help="Configuration file", default="/etc/conftool/config.yaml"
    )
    parser.add_argument("--debug", action="store_true")
    command = parser.add_subparsers(help="Command to execute", dest="command")
    command.required = True
    # Sync command
    # Synchronize entities from yaml files to the datastore
    # Example: requestctl sync --purge ipblock .
    sync = command.add_parser("sync", help="Synchronize data in the git repo to etcd.")
    sync.add_argument(
        "--git-repo", "-g", help="location on disc of the git repository", required=True
    )
    sync.add_argument(
        "object_type", help="What object type to sync", choices=SCHEMA.keys()
    )
    sync.add_argument(
        "--purge", "-p", help="Also delete removed objects.", action="store_true"
    )
    sync.add_argument(
        "--interactive",
        "-i",
        help="Interactively sync objects if needed.",
        action="store_true",
    )
    # Dump command. Dumps the datastore to a directory that can be used with sync.
    dump = command.add_parser(
        "dump",
        help="Dumps the content of the datastore to a format that can be used by sync.",
    )
    dump.add_argument(
        "--git-repo", "-g", help="location on disc of the git repository", required=True
    )
    dump.add_argument(
        "object_type", help="What object type to sync", choices=SCHEMA.keys()
    )
    # Enable command. Enables a request action.
    enable = command.add_parser("enable", help="Turns on a specific action")
    enable.add_argument("action", help="Action to enable")
    # Disable command. Disables a request action
    disable = command.add_parser("disable", help="Turns off a specific action")
    disable.add_argument("action", help="Action to enable")
    # Get command
    # Gets either all or one specific object from the datastore, outputs in various formats
    # Examples:
    # requestctl get action
    # requestctl get action cache-text/block_cloud
    # requestctl get action cache-text/block_cloud -o yaml
    get = command.add_parser("get", help="Get an object")
    get.add_argument("object_type", help="What objects to get", choices=SCHEMA.keys())
    get.add_argument(
        "object_path", help="The full name of the object", nargs="?", default=""
    )
    get.add_argument(
        "-o",
        "--output",
        help="Choose the format for output: pretty, json, yaml. "
        "Pretty output is disabled for actions at the moment.",
        choices=["pretty", "json", "yaml"],
        default="pretty",
    )
    # Log command. Outputs a typical varnishncsa command to log the selected action
    log = command.add_parser(
        "log", help="Get the varnishncsa to log requests matching an object."
    )
    log.add_argument(
        "object_path",
        help="The full name of the object",
    )
    return parser.parse_args(args)


def main():
    """Run the tool."""
    logger = logging.getLogger("reqctl")
    options = parse_args(sys.argv[1:])
    rq = Requestctl(options)
    try:
        rq.run()
    except RequestctlError as e:
        logger.error(e)
        sys.exit(1)
