from conftool import drivers
from conftool.kvobject import Entity, FreeSchemaEntity


class MockDriver(drivers.BaseDriver):

    def __init__(self, config):
        self.base_path = '/base_path/v2'


class MockBackend(object):

    def __init__(self, config):
        self.config = config
        self.driver = MockDriver(config)


class MockEntity(Entity):
    _tags = ['foo', 'bar']
    _schema = {'a': int, 'b': str}

    @classmethod
    def base_path(cls):
        return 'Mock/entity'

    def get_default(self, what):
        if what == 'a':
            return 1
        else:
            return 'FooBar'


class MockFreeEntity(FreeSchemaEntity):
    _tags = ['foo', 'bar']
    _schema = {'a': int, 'b': str}

    @classmethod
    def base_path(cls):
        return 'Mock/entity'

    def get_default(self, what):
        if what == 'a':
            return 1
        else:
            return 'FooBar'
