import sys
import os
from conftool import _log


class Backend(object):

    def __init__(self, config):
        self.config = config
        dir = os.path.dirname(__file__)
        driver_file = os.path.join(
            dir, "drivers/{}.py".format(self.config.driver))
        ctx = {}
        try:
            execfile(driver_file, ctx)
            cls = ctx['Driver']
            self.driver = cls(config)
        except Exception as e:
            _log.critical("Could not load driver %s: %s",
                          self.config.driver, e, exc_info=True)
            sys.exit(3)
