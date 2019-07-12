import logging
import os
import pwd
import socket

import yaml

from pkg_resources import get_distribution, DistributionNotFound

try:
    __version__ = get_distribution(__name__).version
    """The version of the installed conftool module."""
except DistributionNotFound:
    pass


_log = logging.getLogger(__name__)


class IRCSocketHandler(logging.Handler):
    """Log handler for logmsgbot on #wikimedia-operation.

    Sends log events to a tcpircbot server for relay to an IRC channel.

    Adapted from scap
    """

    def __init__(self, host, port, timeout=1.0):
        """
        :param host: tcpircbot host
        :type host: str
        :param port: tcpircbot listening port
        :type port: int
        :param timeout: timeout for sending message
        :type timeout: float
        """
        super().__init__()
        self.addr = (host, port)
        self.level = logging.INFO
        self.timeout = timeout
        try:
            self.user = os.getlogin()
        except OSError:
            self.user = pwd.getpwuid(os.getuid())[0]

    def emit(self, record):
        message = '!log %s@%s %s' % (
            self.user,
            socket.gethostname(),
            record.getMessage())
        message = message.encode('utf-8')

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect(self.addr)
            sock.sendall(message)
            sock.close()
        except (socket.timeout, socket.error, socket.gaierror):
            self.handleError(record)


_irc = logging.getLogger('conftool.announce')


def setup_irc(config):
    # Only one handler should be present
    if _irc.handlers:
        return

    if config.tcpircbot_host and config.tcpircbot_port:
        _irc.addHandler(
            IRCSocketHandler(
                config.tcpircbot_host,
                config.tcpircbot_port
            )
        )
    else:
        _log.warning('Skipped configuration of IRC handler, invalid parameters: host=%s, port=%d',
                     config.tcpircbot_host, config.tcpircbot_port)


def yaml_log_error(name, exc, critical):
    if critical:
        logger = _log.critical
    else:
        logger = _log.info
    if type(exc) is IOError:
        if exc.errno == 2:
            logger("File %s not found", exc.filename)
        else:
            logger("I/O error while reading from %s", exc.filename)
    else:
        logger("Error parsing yaml file %s: %s", name, exc)


def yaml_safe_load(filename, default=None):
    try:
        with open(filename, 'r') as f:
            return yaml.safe_load(f)
    except (IOError, yaml.YAMLError) as exc:
        critical = (default is None)
        yaml_log_error(filename, exc, critical)
        if critical:
            raise
        else:
            return default


def get_username():
    """Detect and return the name of the effective running user even if run as root.

    Returns:
        str: the name of the effective running user or ``-`` if unable to detect it.

    """
    # TODO: add test coverage, although the same code is fully tested in Spicerack
    user = os.getenv('USER')
    sudo_user = os.getenv('SUDO_USER')

    if sudo_user is not None and sudo_user != 'root':
        return sudo_user

    if user is not None:
        return user

    return '-'
