import logging
import os
import pwd
import socket
import sys

import yaml

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
        super(IRCSocketHandler, self).__init__()
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

        if sys.version_info[0] != 2:  # Python 3+
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
    _irc.addHandler(
        IRCSocketHandler(
            config.tcpircbot_host,
            config.tcpircbot_port
        )
    )


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
