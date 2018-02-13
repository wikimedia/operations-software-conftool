from conftool import drivers
from conftool.kvobject import KVObject, Entity, FreeSchemaEntity, JsonSchemaEntity
from conftool.types import get_validator, JsonSchemaLoader

class MockDriver(drivers.BaseDriver):

    def __init__(self, config):
        self.base_path = '/base_path/v2'


class MockBackend(object):

    def __init__(self, config):
        self.config = config
        self.driver = MockDriver(config)


class MockBasicEntity(KVObject):
    _tags = ['A', 'B', 'C', 'D']
    _schema = {'val': get_validator ('any')}

    @classmethod
    def base_path(cls):
        return 'base_path'

    @property
    def key(self):
        return 'a/b/c/d/e'

    @property
    def dir(self):
        return 'a'


class MockEntity(Entity):
    _tags = ['foo', 'bar']
    _schema = {'a': get_validator('int'), 'b': get_validator('string')}

    @classmethod
    def base_path(cls):
        return 'Mock/entity'

    def get_default(self, what):
        if what == 'a':
            return 1
        else:
            return 'FooBar'


class MockJsonEntity(JsonSchemaEntity):
    _tags = ['foo', 'bar']
    _schema = {'val': get_validator('any')}
    # load a catchall rule for a string
    loader = JsonSchemaLoader(
        base_path='conftool/tests/fixtures/schemas',
        rules={'catchall': {'schema': 'val.schema', 'selector': 'name=.*'}}
    )

    @classmethod
    def base_path(cls):
        return 'Mock/entity'

    def get_default(self, what):
        if what == 'val':
            return ''
        else:
            return 'FooBar'


class MockFreeEntity(FreeSchemaEntity):
    _tags = ['foo', 'bar']
    _schema = {'a': get_validator('int'), 'b': get_validator('string')}

    @classmethod
    def base_path(cls):
        return 'Mock/entity'

    def get_default(self, what):
        if what == 'a':
            return 1
        else:
            return 'FooBar'
