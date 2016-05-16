import json
import re
import unittest

import mock

from conftool import configuration, drivers
from conftool.kvobject import KVObject
from conftool.tests.unit import MockBackend, MockEntity, MockFreeEntity
from conftool.types import get_validator

class TestKVObject(unittest.TestCase):

    def setUp(self):
        KVObject.backend = MockBackend({})
        KVObject.config = configuration.Config(driver="")
        self.entity = MockEntity('Foo', 'Bar', 'test')

    def test_kvpath(self):
        """
        Test `KVObject.kvpath`
        """
        self.assertEqual('Mock/entity/bar/baz',
                         self.entity.kvpath('bar', 'baz'))

    def test_find_found(self):
        """
        Test `KVObject.find`
        """
        # Find returns an object if found
        KVObject.backend.driver.find_in_path = mock.Mock(return_value=[('Foo', 'Bar', 'test')])
        res = [ent for ent in MockEntity.find('test')]
        KVObject.backend.driver.find_in_path.assert_called_with('Mock/entity', 'test')
        self.assertEqual(len(res), 1)

    def test_find_not_found(self):
        """
        Test `KVObject.find` returns an empty list if nothing is found
        """
        # Empty list of results if nothing found
        KVObject.backend.driver.find_in_path = mock.Mock(return_value=[])
        res = [ent for ent in MockEntity.find('test')]
        self.assertEqual(res, [])

    def test_find_bad_data(self):
        """
        Test `KvObject.find` if bad objects are returned, an exception will be
        raised
        """
        MockEntity.backend.driver.find_in_path = mock.Mock(return_value=[('Foo',
                                                                          'test')])
        with self.assertRaises(ValueError):
            for _ in MockEntity.find('test'):
                pass

    def test_query_success(self):
        """
        Test `KvObject.query` finds a valid result
        """
        MockEntity.backend.driver.all_keys = mock.Mock(
            return_value=[['Foo', 'Bar', 'test'], ['Foo', 'Baz', 'test1']]
        )
        res = [el for el in MockEntity.query({'bar': re.compile('Bar')})]
        self.assertEqual('test', res[0].name)
        self.assertEqual(1, len(res))
        res = [el for el in MockEntity.query({'name': re.compile('tes.*')})]
        self.assertEqual(2, len(res))

    def test_query_no_result(self):
        """
        Test `KvObject.query` returns an empty list when no result is available
        """
        MockEntity.backend.driver.all_keys = mock.Mock(
            return_value=[['Foo', 'Bar', 'test'], ['Foo', 'Baz', 'test1']]
        )
        res = [el for el in MockEntity.query({'bar': re.compile('Far')})]
        self.assertEqual([], res)

    def test_properties(self):
        self.assertEqual(self.entity.name, 'test')
        self.assertEqual(self.entity.key, 'Mock/entity/Foo/Bar/test')
        self.assertEqual(self.entity.tags, {'foo': 'Foo', 'bar': 'Bar'})

    def test_fetch(self):
        MockEntity.backend.driver.read = mock.Mock(return_value={'a': 1, 'b': 'b-val'})
        with mock.patch('conftool.tests.unit.MockEntity.from_net') as mocker:
            obj = MockEntity('Foo', 'Bar', 'test')
            mocker.assert_called_with({'a': 1, 'b': 'b-val'})
            # Non-existent key?
            MockEntity.backend.driver.read.side_effect = drivers.NotFoundError('test')
            MockEntity('Foo', 'Bar', 'test')
            mocker.assert_called_with(None)

    def test_write(self):
        MockEntity.backend.driver.write = mock.Mock(return_value={'a': 5, 'b': 'meh'})
        obj = MockEntity('Foo', 'Baz', 'new')
        res = obj.write()
        MockEntity.backend.driver.write.assert_called_with(
            'Mock/entity/Foo/Baz/new', {'a': 1, 'b': 'FooBar'})
        self.assertEqual(res, {'a': 5, 'b': 'meh'})
        obj = MockEntity('Foo', 'Baz', 'new')
        res = obj.write()
        # A driver exception gets passed to us
        MockEntity.backend.driver.write.side_effect = ValueError('bad json, bad!')
        self.assertRaises(ValueError, obj.write)

    def test_delete(self):
        MockEntity.backend.driver.delete = mock.Mock(return_value=None)
        obj = MockEntity('Foo', 'Baz', 'new')
        obj.delete()
        MockEntity.backend.driver.delete.assert_called_with('Mock/entity/Foo/Baz/new')
        # A driver exception gets passed to us
        MockEntity.backend.driver.delete.side_effect = drivers.BackendError('something')
        self.assertRaises(drivers.BackendError, obj.delete)

    def test_parse_tags(self):
        # Correct tags list
        taglist = ["bar=Bar", "foo=Foo"]
        self.assertEqual(MockEntity.parse_tags(taglist), ['Foo', 'Bar'])
        # Additional tags are just discarded
        taglist = ["a=n", "bar=Bar", "foo=Foo"]
        self.assertEqual(MockEntity.parse_tags(taglist), ['Foo', 'Bar'])

    def test_update(self):
        self.entity.write = mock.Mock()
        self.entity._set_value = mock.Mock(side_effect=self.entity._set_value)
        # Setting a value not in the schema doesn't do anything
        self.entity.update({'c': 'meh'})
        self.entity._set_value.assert_not_called()
        # Setting a value in the schema does set it
        self.entity.update({'a': 10})
        self.entity._set_value.assert_called_with('a', get_validator('int'), {'a': 10},
                                                  set_defaults=False)
        self.entity.write.assert_called_with()

    def test_to_net(self):
        self.entity.a = 100
        self.entity.b = 'meoow'
        self.assertEqual(self.entity._to_net(), {'a': 100, 'b': 'meoow'})
        obj = MockEntity('a', 'b', 'c')
        self.assertEqual(obj._to_net(), {'a': 1, 'b': 'FooBar'})

    def test_from_net(self):
        obj = MockEntity('a', 'b', 'c')
        obj.from_net({'a': 256})
        self.assertEqual(obj._to_net(), {'a': 256, 'b': 'FooBar'})

    def test_set_value(self):
        with mock.patch('conftool.tests.unit.MockEntity.fetch'):
            obj = MockEntity('a', 'b', 'c')
        # set an existing value
        obj._set_value('a', get_validator('int'), {'a': 256})
        self.assertEqual(obj.a, 256)
        # Set an inexistent value with no defaults
        obj._set_value('c', get_validator('string'), {})
        self.assertEqual(obj.c, 'FooBar')

    def test_str(self):
        teststr = json.loads(str(self.entity))
        self.assertEqual(sorted(teststr.keys()), ['tags', 'test'])
        self.assertEqual(teststr['tags'], 'foo=Foo,bar=Bar')
        self.assertEqual(teststr['test']['a'], 1)

    def test_eq(self):
        ent = MockEntity('Foo', 'Bar', 'test')
        self.assertEqual(ent, self.entity)
        ent1 = MockEntity('Foo', 'Bar', 'test1')
        self.assertNotEqual(ent1, self.entity)
        ent2 = MockEntity('Foo2', 'Bar', 'test')
        self.assertNotEqual(ent2, self.entity)
        ent.a = 256
        self.assertNotEqual(ent, self.entity)


class TestFreeSchemaObject(unittest.TestCase):

    def setUp(self):
        KVObject.backend = MockBackend({})
        KVObject.config = configuration.Config(driver="")

    def test_init(self):
        a = MockFreeEntity('Foo', 'Bar', 'test', some_key="some_value")
        self.assertEqual(a._schemaless, {'some_key': "some_value"})

    def test_to_net(self):
        a = MockFreeEntity('Foo', 'Bar', 'test', some_key="some_value")
        a.a = 240
        self.assertEqual(a._to_net(),
                         {'a': 240, 'b': 'FooBar', 'some_key': 'some_value'})

    def test_from_net(self):
        a = MockFreeEntity('Foo', 'Bar', 'test', some_key="some_value")
        a.from_net({'some_key': 'another_value', 'm': 5})
        self.assertEqual(a.a, 1)
        self.assertEqual(a._schemaless['some_key'], 'another_value')

    def test_changed(self):
        a = MockFreeEntity('Foo', 'Bar', 'test', some_key="some_value")

        data = {'a': 1, 'b': 'FooBar', 'some_key': 'some_value'}
        self.assertEqual(data, a._to_net())
        self.assertFalse(a.changed(data))
        a.a = 2
        self.assertTrue(a.changed(data))
