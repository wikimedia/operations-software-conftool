import logging
import os
import pwd
import socket

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
