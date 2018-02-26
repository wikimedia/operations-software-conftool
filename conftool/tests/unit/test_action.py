import os

import mock
import unittest

from conftool import action, configuration
from conftool.action import get_action, ActionError, GetAction, DelAction, \
    SetAction, EditAction, ActionValidationError
from conftool.kvobject import KVObject
from conftool.tests.unit import MockBackend, MockEntity
from conftool.types import get_validator

class TestAction(unittest.TestCase):

    def setUp(self):
        KVObject.backend = MockBackend({})
        KVObject.config = configuration.Config(driver="")
        self.entity = MockEntity('Foo', 'Bar', 'test')
        self.entity.exists = True

    def test_get_action(self):
        """
        Test initialization of the Action object
        """
        # Get action
        a = get_action(self.entity, 'get')
        self.assertEqual(a.entity, self.entity)
        self.assertEqual(a.__class__, GetAction)
        # Delete action
        a = get_action(self.entity, 'delete')
        self.assertEqual(a.__class__, DelAction)
        # Set from file
        with mock.patch('conftool.action.SetAction._from_file') as mocker:
            values = {'a': 10, 'b': 'test test'}
            mocker.return_value = values
            a = get_action(self.entity, 'set/@filename.yaml')
            self.assertEqual(a.__class__, SetAction)
            self.assertEqual(a.args, values)
        # Set from cli
        a = get_action(self.entity, 'set/a=10:b=test test')
        self.assertEqual(a.__class__, SetAction)
        self.assertEqual(a.args, {'a': '10', 'b': 'test test'})
        self.assertRaises(ActionError, get_action, self.entity, 'set/a=1:')
        a = get_action(self.entity, 'set/a=true:b=a,foo,bar')
        self.assertEqual(a.args, {'a': 'true', 'b': 'a,foo,bar'})
        # Edit
        a = get_action(self.entity, 'edit')
        self.assertEqual(a.__class__, EditAction)
        self.assertEqual(a.DEFAULT_EDITOR, '/usr/bin/editor')
        self.assertEqual(a.edited, {})
        self.assertEqual(a.temp, None)
        # Unknown
        self.assertRaises(ActionError, get_action, self.entity, 'unicorns!')

    def test_from_cli(self):
        """
        Test parsing of cli-provided arguments
        """
        a = get_action(self.entity, 'set/bar=ac')
        a.entity._schema['bar'] = get_validator('list')
        self.assertEqual(a._from_cli({'bar': 'abc,def,ghi'}),
                         {'bar': ['abc', 'def', 'ghi']})
        a.entity._schema['bar'] = get_validator('bool')
        self.assertEqual(a._from_cli({'bar': 'false'}),
                         {'bar': False})
        self.assertEqual(a._from_cli({'bar': 'true'}),
                         {'bar': True})
        self.assertRaises(ValueError, a._from_cli, {'bar': 'popcorn!'})
        a.entity._schema['bar'] = get_validator('dict')
        self.assertRaises(ValueError, a._from_cli, {'bar': 'popcorn!'})
        del a.entity._schema['bar']

    def test_run(self):
        a = get_action(self.entity, 'get')
        a.entity.fetch = mock.Mock()
        a.entity.exists = False
        self.assertEqual(a.run(), "test not found")
        a.entity.exists = True
        self.assertEqual(a.run()[2:6], 'test')
        a = get_action(self.entity, 'delete')
        a.entity.exists = True
        self.assertEqual(a.run(), 'Deleted (\'MockEntity\',) test.')
        # set action will fail if the data doesn't validate
        a = get_action(self.entity, 'set/a=1')
        self.entity.validate = mock.Mock(side_effect=ValueError)
        self.assertRaises(ActionValidationError, a.run)


    @mock.patch('subprocess.call')
    @mock.patch('conftool.action.yaml_safe_load')
    def test_edit(self, yaml_mock, mocker):
        a = get_action(self.entity, 'edit')
        a.temp = 'test'
        yaml_mock.return_value = {'a': 1, 'b': 'hello'}
        a._edit()
        mocker.assert_called_with(['/usr/bin/editor', 'test'])
        self.assertEqual(a.edited, {'a': 1, 'b': 'hello'})
        os.environ['EDITOR'] = 'testmewell --verbose -t'
        a._edit()
        mocker.assert_called_with(['testmewell', '--verbose', '-t', 'test'])

    def test_edit_to_file(self):
        self.entity.fetch = mock.MagicMock()
        self.entity._to_net = mock.MagicMock(return_value=["test"])
        a = get_action(self.entity, 'edit')
        a.temp = 'test'
        with mock.patch(
                'conftool.action.open',
                mock.mock_open(read_data='')
        ) as mockopen:
            a._to_file()
            mockopen.assert_called_with('test', 'wb')
            self.entity.fetch.assert_called_with()
            file_handle = mockopen.return_value.__enter__.return_value
            file_handle.write.assert_has_calls([
                mock.call("["),
                mock.call("test"),
                mock.call("]"),
                mock.call("\n")
            ])


    def test_edit_run(self):
        a = get_action(self.entity, 'edit')
        a._to_file = mock.MagicMock()
        a._edit = mock.MagicMock()
        a.edited = {'a': 1, 'b': 'hello'}
        a.temp = 'testunlink'
        with mock.patch('conftool.action.os.unlink') as unlinker:
            self.entity.update = mock.MagicMock()
            self.assertEqual(a.run(), "Entity Foo/Bar/test successfully updated")
            self.entity.update.assert_called_with(a.edited)
            a._edit.assert_called_once()
        exception = ValueError('test me')
        self.entity.validate = mock.MagicMock(
            side_effect=[exception, None]
        )
        a._check_amend = mock.MagicMock()
        with mock.patch('conftool.action.os.unlink') as unlinker:
            self.assertEqual(a.run(), "Entity Foo/Bar/test successfully updated")
            a._check_amend.assert_called_with(exception)
            unlinker.assert_called_with(a.temp)

    def test_set_from_file(self):
        a = get_action(self.entity, 'set/a=1')
        with mock.patch('conftool.action.yaml_safe_load') as mocker:
            mocker.return_value = {'a': 1}
            self.assertEqual(a._from_file('@test'), {'a': 1})
            mocker.assert_called_with('test')
            mocker.side_effect = Exception('test')
            self.assertRaises(ActionError, a._from_file, '@test')
