from conftool import drivers


class MockDriver(drivers.BaseDriver):

    def __init__(self, config):
        self.base_path = '/base_path/v2'


class MockBackend(object):

    def __init__(self, config):
        self.config = config
        self.driver = MockDriver(config)
