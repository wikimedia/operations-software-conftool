import argparse
import logging
import sys

from conftool.extensions.dbconfig.cli import DbConfigCli


def parse_args(cmdline):
    parser = argparse.ArgumentParser(
        description='Tool to perform simple operations of configuration for databases in mediawiki',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--config', help='Config file', default='/etc/conftool/config.yaml')
    parser.add_argument('--debug', action='store_true', default=False, help='print debug info')
    # TODO: how necessary / safe is this option?
    parser.add_argument('--quiet', action='store_true', dest='quiet',
                        default=False, help='Do not announce the change to IRC')
    parser.add_argument('--schema', default='/etc/conftool/schema.yaml',
                        help='Schema file that defines additional object types')
    parser.add_argument('-s', '--scope', help='Refer any action to this datacenter.')
    # Hidden argument, needed for subclassing `conftool.cli.tool.ToolCli`
    parser.add_argument('--object_type', default='mwconfig', help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(
        help='Object to act upon: section, instance, or config',
        dest='object_name'
    )
    subparsers.required = True

    instance = subparsers.add_parser('instance', help='Act on a database instance')
    section = subparsers.add_parser('section', help='Act on a database section')
    config = subparsers.add_parser('config', help='Interact with the proper MediaWiki config')

    # dbconfig instance
    # Possible actions: get, depool, pool, edit
    instance.add_argument('instance_name', metavar='LABEL', help='The label of the instance')
    commands = instance.add_subparsers(help='Command to execute', dest='command')
    commands.required = True

    commands.add_parser('get', help='Get information about the database instance')
    commands.add_parser('edit', help='Edit information about the database instance')

    depool = commands.add_parser(
        'depool',
        help='Depool the instance, either completely or from a specified section/group')
    depool.add_argument('--section', help='If you want to indicate a specific section')
    depool.add_argument('--group', help='If within a section you want to pick one group')

    pool = commands.add_parser(
        'pool', help='Pool the instance, either completely or from a specified section/group')
    pool.add_argument('-p', '--percentage', default=100,  type=int,
                      help='The percentage of pooling to set')
    pool.add_argument('--section', help='If you want to indicate a specific section')
    pool.add_argument('--group',
                      help='If within a section you want to pick one group')

    weight = commands.add_parser('set-weight', help='Set the weight of a specific section/group')
    weight.add_argument('--section',
                        help='If you want to indicate a specific section', required=True)
    weight.add_argument('--group', help='If within a section you want to pick one group')
    weight.add_argument('weight', help='The new weight', type=int)

    # dbconfig section
    # Possible actions are get, edit, set-master, ro, rw
    section.add_argument('section_name', metavar='LABEL',
                         help=('The label of the section. Exclusively with the "get" action, the '
                               'special label "all" can be used to select all sections'))
    # TODO: validation on the section_name?
    commands = section.add_subparsers(help='Command to execute', dest='command')
    commands.required = True

    get = commands.add_parser('get', help='Get information about the database instance')
    get.add_argument('-m', '--mediawiki', action='store_true',
                     help='Print the information in PHP format')

    commands.add_parser('edit', help='Edit information about the database instance')

    master = commands.add_parser('set-master', help='Set a new master for the specified section')
    master.add_argument('instance_name', metavar='INSTANCE',
                        help='Instance to set as the master')

    ro = commands.add_parser('ro', help='Set the section to read-only')
    ro.add_argument('reason', help='Message to show to the users for the read-only phase')
    commands.add_parser('rw', help='Set the section to read-write')

    # dbconfig config
    # Possible actions are commit, get
    commands = config.add_subparsers(help='Command to execute', dest='command')
    commands.required = True
    commit = commands.add_parser('commit',
                                 help='Commit the configuration for consumption by MediaWiki')
    commit.add_argument('-b', '--batch', action='store_true',
                        help='Do not ask for visual diff confirmation')
    commands.add_parser('get', help='Get the configuration from mediawiki-config')
    return parser.parse_args(cmdline)


def main(cmdline=None):
    if cmdline is None:
        cmdline = sys.argv[1:]
    # TODO: above probably not needed, argparse will DTRT if given None

    args = parse_args(cmdline)
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARN)
    # TODO: INFO logging by default? or is that too noisy?

    cli = DbConfigCli(args)
    cli.setup()
    success = cli.run_action()
    if success:
        return 0

    return 1


if __name__ == '__main__':
    sys.exit(main())
