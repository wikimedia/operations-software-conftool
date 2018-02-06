import unittest

import mock

from conftool import types, configuration
from conftool.kvobject import KVObject
from conftool.tests.unit import MockEntity, MockBackend


class FieldValidatorsTestCase(unittest.TestCase):

    def test_str_validator(self):
        validator = types.get_validator('string')
        input_string = "abcdef gz"
        self.assertEqual(input_string, validator(input_string))
        input_list = [1, 2]
        self.assertEqual('[1, 2]', validator(input_list))
        self.assertEqual('string', validator.expected_type)

    def test_int_validator(self):
        validator = types.get_validator('int')
        # When a number is passed, as a string
        self.assertEqual(101, validator("101"))
        # when a random string gets passed
        self.assertRaises(ValueError, validator, "neoar sds")

    def test_list_validator(self):
        validator = types.get_validator("list")
        self.assertEqual(['abc', 1, 'may'], validator(['abc',1,'may']))
        self.assertEqual([], validator('abcdesf'))
        self.assertEqual([], validator(''))

    def test_bool_validator(self):
        validator = types.get_validator("bool")
        self.assertEqual(True, validator(True))
        self.assertEqual(False, validator(False))
        self.assertRaises(ValueError, validator, 'definitely maybe')

    def test_enum_validator(self):
        validator = types.get_validator("enum:a|b|c")
        self.assertEqual('c', validator('c'))
        self.assertRaises(ValueError, validator, 'd')

    def test_any_validator(self):
        validator = types.get_validator("any")
        self.assertEqual("a string", validator("a string"))
        self.assertEqual(['a', 'list'], validator(['a', 'list']))
        self.assertEqual({'a': 'dict'}, validator({'a': 'dict'}))

        class Foo(object):
            pass

        self.assertRaises(ValueError, validator, Foo())


class SchemaRuleTestCase(unittest.TestCase):

    def setUp(self):
        KVObject.backend = MockBackend({})
        KVObject.config = configuration.Config(driver="")

    def test_initialize(self):
        """
        Test initialization of a schema rule
        """
        t = types.SchemaRule('testname', 'testkey=test.*,name=foo.*', 'testschema')
        self.assertEqual(t.name, 'testname')
        self.assertEqual(t.path, 'testschema')
        self.assertEqual(set(t.selectors.keys()), set(['name', 'testkey']))
        self.assertIsNone(t._schema)

    def test_schema(self):
        t = types.SchemaRule(
            'testname', 'name=foo.*',
            'conftool/tests/fixtures/schemas/runner_horse.schema'
        )
        self.assertEqual(t.schema['type'], 'object')
        self.assertEqual(t.schema['properties']['nick']['type'], 'string')

    def test_match(self):
        m = MockEntity('FOO', 'BARBAR', 'FooBar')
        t = types.SchemaRule('testname', 'name=Foo.*', 'random')
        self.assertTrue(t.match(m.tags, m._name))
        t = types.SchemaRule('testname', 'bar=barbar', 'random')
        self.assertFalse(t.match(m.tags, m._name))

    def test_validate(self):
        t = types.SchemaRule(
            'testname', 'name=foo.*',
            'conftool/tests/fixtures/schemas/runner_horse.schema'
        )
        valid_data = {
            "height": 166, "nick": "Varenne",
            "custom": {"wins": 62, "starts": 73}
        }
        # Valid data doesn't raise any exception
        self.assertTrue(t.validate(valid_data))

        # Empty data will raise an exception
        empty = {}
        self.assertRaises(ValueError, t.validate, empty)
        invalid_data = { "height": 1, "nick": "bogus", "wins": 62}
        self.assertRaises(ValueError, t.validate, invalid_data)


class JsonSchemaLoaderTestCase(unittest.TestCase):
    @mock.patch('conftool.types.SchemaRule', autospec=True)
    def test_init(self, rule):
        instance = mock.MagicMock()
        rule.return_value = instance
        s = types.JsonSchemaLoader(
            base_path='conftool/tests/fixtures/schemas',
            rules={'catchall': {'schema': 'test.schema', 'selector': 'name=.*'}}
        )
        rule.assert_called_with('catchall', 'name=.*', 'conftool/tests/fixtures/schemas/test.schema')
        self.assertEqual(s.rules, [instance])

    @mock.patch('conftool.types.SchemaRule', autospec=True)
    def test_rules_for(self, rule):
        instance = mock.MagicMock()
        rule.return_value = instance
        s = types.JsonSchemaLoader(
            base_path='conftool/tests/fixtures/schemas',
            rules={'catchall': {'schema': 'test.schema', 'selector': 'name=.*'}}
        )
        instance.match.return_value = True
        self.assertEqual(s.rules_for({'a': 'foo', 'b': 'bar'}, 'test'), [instance])
        # Returns an empty list if nothing matches.
        instance.match.return_value = False
        self.assertEqual(s.rules_for({'a': 'foo', 'b': 'bar'}, 'test'), [])
        # exceptions are not caught
        instance.match.side_effect = ValueError('meh')
        self.assertRaises(ValueError, s.rules_for, {'a': 'foo', 'b': 'bar'}, 'test')

    def test_get_json_schema(self):
        s = types.get_json_schema(
            {
                'base_path': "conftool/tests/fixtures/schemas",
                'rules': {
                    'catchall': {
                        'selector': 'name=.*',
                        'schema': 'string.schema'
                    }
                }
            }
        )
        self.assertEqual(len(s.rules), 1)
