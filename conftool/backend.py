import sys
import os


class Backend(object):

    def __init__(self, config):
        self.config = config
        dir = os.path.dirname(__file__)
        driver_file = os.path.join(dir,"drivers/{}.py".format(self.config.driver))
        ctx = {}
        try:
            execfile(driver_file, ctx)
            cls = ctx['Driver']
            self.driver = cls(config)
        except Exception as e:
            raise
            # TODO: log the error
            sys.exit(3)
