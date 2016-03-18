import logging
_log = logging.getLogger(__name__)


def choice(*args):
    def is_in(x):
        if x not in args:
            raise ValueError("{} not in '{}'".format(x, ",".join(args)))
        return x
    return is_in
