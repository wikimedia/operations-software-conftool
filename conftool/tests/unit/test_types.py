import unittest

from conftool import types


class FieldValidatorsTestCase(unittest.TestCase):

    def test_str_validator(self):
        validator = types.get_validator('string')
        input_string = "abcdef gz"
        self.assertEquals(input_string, validator(input_string))
        input_list = [1, 2]
        self.assertEquals('[1, 2]', validator(input_list))
        self.assertEqual('string', validator.expected_type)

    def test_int_validator(self):
        validator = types.get_validator('int')
        # When a number is passed, as a string
        self.assertEquals(101, validator("101"))
        # when a random string gets passed
        self.assertRaises(ValueError, validator, "neoar sds")

    def test_list_validator(self):
        validator = types.get_validator("list")
        self.assertEquals(['abc', 1, 'may'], validator(['abc',1,'may']))
        self.assertEquals([], validator('abcdesf'))
        self.assertEquals([], validator(''))

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
