import os
import unittest

import mock
import yaml

from conftool import loader
from conftool.kvobject import KVObject, Entity, FreeSchemaEntity
from conftool import configuration
from conftool.tests.unit import MockBackend

test_base = os.path.realpath(os.path.join(
    os.path.dirname(__file__), os.path.pardir))


class FactoryTestCase(unittest.TestCase):
    def setUp(self):
        KVObject.backend = MockBackend({})
        KVObject.config = configuration.Config(driver="")
        self.base_defs = {
            'tags': ['test', 'example'],
            'schema': {
                'astring': {'type': 'string', 'default': 'foo'},
                'alist': {'type': 'list', 'default': []},
                'abool': {'type': 'bool', 'default': False},
                'anenum': {'type': 'enum:a|b|c|foo', 'default': 'foo'}
            },
            'path': 'example.org',
        }

    def test_base_path(self):
        """Test that base path is correct"""
        entity = loader.factory('Test', self.base_defs)
        self.assertEqual(entity.base_path(), 'example.org')

    def test_class_type(self):
        """Test the correct class is subclassed"""
        entity = loader.factory('Test', self.base_defs)
        assert(issubclass(entity, Entity))
        self.base_defs['free_form'] = True
        entity = loader.factory('Test', self.base_defs)
        assert(issubclass(entity, FreeSchemaEntity))

    def test_properties(self):
        """Test that all properties are statically set correctly"""
        entity = loader.factory('Test', self.base_defs)
        self.assertListEqual(entity._tags, ['test', 'example'])
        self.assertEqual(sorted(entity._schema.keys()), sorted(self.base_defs['schema'].keys()))

    def test_entity(self):
        """Test that an entity works as expected"""
        Test = loader.factory('Test', self.base_defs)
        with self.assertRaises(ValueError):
            t = Test('mytest')
        t = Test('entity', 'foo', 'mytest')
        self.assertDictEqual(t.tags, {'test': 'entity', 'example': 'foo'})
        self.assertEqual(t.key, 'example.org/entity/foo/mytest')
        self.assertEqual(Test.dir('a', 'b'), 'example.org/a/b')
        self.assertEqual(t.astring, 'foo')
        self.assertEqual(t.anenum, 'foo')

        with self.assertRaises(ValueError):
            Test.dir('a', 'b', 'c')

    def test_depends(self):
        """Test that dependencies are set as expected"""
        Test = loader.factory('Test', self.base_defs)
        self.assertEqual(Test.depends, [])
        d = self.base_defs
        d['depends'] = ['a', 'b']
        Test = loader.factory('Test', d)
        self.assertEqual(Test.depends, ['a', 'b'])


class SchemaTestCase(unittest.TestCase):
    def setUp(self):
        KVObject.backend = MockBackend({})
        KVObject.config = configuration.Config(driver="")
        self.schema_file = os.path.join(test_base, 'fixtures', 'schema.yaml')

    def test_load_schema(self):
        schema = loader.Schema.from_file(self.schema_file)
        self.assertEqual(set(schema.entities.keys()),
                          set(['node', 'pony', 'service', 'unicorn', 'horse']))
        n = schema.entities['pony']('violet', 'female', 'foobar')
        n.hair_color = "violet"
        self.assertEqual(n.accessories, [])
        self.assertEqual(n.tags, {'color': 'violet', 'gender': 'female'})
        pinkunicorn = schema.entities['unicorn']('pink', 'undefined', 'foobar')
        self.assertEqual(pinkunicorn.magic, 'rainbows')

    def test_broken_schemas(self):
        """
        Test failure modes for the schema loading
        """
        # Case 1: the file is not present
        schema = loader.Schema.from_file('doesnt.exists')
        self.assertListEqual(sorted(schema.entities.keys()), ['node', 'service'])
        self.assertFalse(schema.has_errors)
        # Case 2: broken file (that means the file includes invalid data)
        schema = loader.Schema.from_file(os.path.join(test_base, 'fixtures',
                                                      'broken_schema.yaml'))
        self.assertListEqual(sorted(schema.entities.keys()), ['node', 'pony', 'service', 'unicorn'])
        self.assertTrue(schema.has_errors)
        # Case 3: invalid yaml
        with mock.patch('conftool.yaml.safe_load') as mocker:
            mocker.side_effect = yaml.YAMLError('something unexpected')
            schema = loader.Schema.from_file(self.schema_file)
            self.assertTrue(schema.has_errors)
        # Case 4: generic exception is *not* handled
        with mock.patch('conftool.yaml.safe_load') as mocker:
            mocker.side_effect = Exception('something unexpected')
            self.assertRaises(Exception, loader.Schema.from_file, self.schema_file)
