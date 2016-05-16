import mock
import unittest

from conftool import configuration
from conftool.action import Action, ActionError
from conftool.kvobject import KVObject
from conftool.tests.unit import MockBackend, MockEntity
from conftool.types import get_validator

class TestAction(unittest.TestCase):

    def setUp(self):
        KVObject.backend = MockBackend({})
        KVObject.config = configuration.Config(driver="")
        self.entity = MockEntity('Foo', 'Bar', 'test')


    def test_init(self):
        """
        Test initialization of the Action object
        """
        # Get action
        a = Action(self.entity, 'get')
        self.assertEqual(a.entity, self.entity)
        self.assertEqual(a.action, 'get')
        self.assertIsNone(a.args)
        # Delete action
        a = Action(self.entity, 'delete')
        self.assertEqual(a.action, 'delete')
        self.assertIsNone(a.args)
        # Set from file
        with mock.patch('conftool.action.Action._from_file') as mocker:
            values = {'a': 10, 'b': 'test test'}
            mocker.return_value = values
            a = Action(self.entity, 'set/@filename.yaml')
            self.assertEqual(a.action, 'set')
            self.assertEqual(a.args, values)
        # Set from cli
        a = Action(self.entity, 'set/a=10:b=test test')
        self.assertEqual(a.action, 'set')
        self.assertEqual(a.args, {'a': '10', 'b': 'test test'})
        self.assertRaises(ActionError, Action, self.entity, 'set/a=1:')
        a = Action(self.entity, 'set/a=true:b=a,foo,bar')
        self.assertEqual(a.args, {'a': 'true', 'b': 'a,foo,bar'})

    def test_from_cli(self):
        """
        Test parsing of cli-provided arguments
        """
        a = Action(self.entity, 'get')
        a.entity._schema['bar'] = get_validator('list')
        self.assertEqual(a._from_cli({'bar': 'abc,def,ghi'}),
                         {'bar': ['abc', 'def', 'ghi']})
        a.entity._schema['bar'] = get_validator('bool')
        self.assertEqual(a._from_cli({'bar': 'false'}),
                         {'bar': False})
        del a.entity._schema['bar']

    def test_run(self):
        a = Action(self.entity, 'get')
        a.entity.fetch = mock.Mock()
        a.entity.exists = False
        self.assertEqual(a.run(), "test not found")
        a.entity.exists = True
        self.assertEqual(a.run()[2:6], 'test')
