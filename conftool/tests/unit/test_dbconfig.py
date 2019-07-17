import os
import re

from collections import defaultdict, OrderedDict
from unittest import mock, TestCase

import yaml

import conftool.extensions.dbconfig as dbconfig
from conftool.extensions.dbconfig.action import ActionResult
from conftool.extensions.dbconfig.cli import DbConfigCli
from conftool.extensions.dbconfig.config import DbConfig
from conftool.extensions.dbconfig.entities import Instance, Section
import conftool.configuration as configuration

from conftool import loader
from conftool.drivers import BackendError
from conftool.kvobject import KVObject
from conftool.tests.integration import test_base
from conftool.tests.unit import MockBackend


class TestParseArgs(TestCase):

    def test_parse_args(self):
        args = dbconfig.parse_args(['instance', 'db1', 'get'])
        self.assertEqual(args.object_name, 'instance')
        self.assertEqual(args.object_type, 'mwconfig')
        self.assertEqual(args.instance_name, 'db1')
        self.assertEqual(args.command, 'get')
        args = dbconfig.parse_args(['instance', 'db1', 'pool'])
        self.assertEqual(args.command, 'pool')
        self.assertEqual(args.section, None)
        self.assertEqual(args.group, None)
        self.assertEqual(args.percentage, None)
        args = dbconfig.parse_args(['instance', 'db1', 'pool', '-p', '75'])
        self.assertEqual(args.percentage, 75)
        args = dbconfig.parse_args(['instance', 'db1', 'depool',
                                    '--section', 's1', '--group', 'vslow'])
        self.assertEqual(args.command, 'depool')
        self.assertEqual(args.section, 's1')
        self.assertEqual(args.group, 'vslow')
        args = dbconfig.parse_args(['instance', 'db1', 'set-weight', '18', '--section', 's1'])
        self.assertEqual(args.command, 'set-weight')
        self.assertEqual(args.section, 's1')
        self.assertEqual(args.weight, 18)
        args = dbconfig.parse_args(['section', 's1', 'get'])
        self.assertEqual(args.object_name, 'section')
        self.assertEqual(args.section_name, 's1')
        args = dbconfig.parse_args(['section', 's1', 'set-master', 'db2'])
        self.assertEqual(args.command, 'set-master')
        self.assertEqual(args.instance_name, 'db2')
        args = dbconfig.parse_args(['section', 's1', 'ro', 'under construction'])
        self.assertEqual(args.command, 'ro')
        self.assertEqual(args.reason, 'under construction')
        args = dbconfig.parse_args(['section', 's1', 'rw'])
        self.assertEqual(args.command, 'rw')
        args = dbconfig.parse_args(['config', 'diff'])
        self.assertEqual(args.object_name, 'config')
        self.assertEqual(args.command, 'diff')
        args = dbconfig.parse_args(['config', 'get'])
        self.assertEqual(args.object_name, 'config')
        self.assertEqual(args.command, 'get')
        args = dbconfig.parse_args(['config', 'generate'])
        self.assertEqual(args.object_name, 'config')
        self.assertEqual(args.command, 'generate')
        args = dbconfig.parse_args(['config', 'commit'])
        self.assertEqual(args.command, 'commit')
        self.assertFalse(args.batch)


class TestDbInstance(TestCase):

    def setUp(self):
        KVObject.backend = MockBackend({})
        KVObject.config = configuration.Config(driver="")
        self.schema = loader.Schema.from_file(
            os.path.join(test_base, 'fixtures', 'dbconfig', 'schema.yaml'))

    def test_init(self):
        """Test initialization of the object"""
        instance = Instance(self.schema)
        self.assertEqual(instance.entity.__name__, 'Dbconfig_instance')
        self.assertIsNone(instance.checker)
        # Validate the example
        example = yaml.safe_load(instance.example)
        obj = instance.entity('dcA', 'example')
        obj.validate(example)

    def test_get_all(self):
        """Test getting all objects"""
        instance = Instance(self.schema)
        instance.entity.query = mock.MagicMock(return_value=[instance.entity('dcA', 'db1')])
        res = [r for r in instance.get_all()]
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].name, 'db1')
        instance.entity.query.assert_called_with({'datacenter': re.compile(r'^\w+$'),
                                                  'name': re.compile(r'^.*$')})

    def test_get(self):
        instance = Instance(self.schema)
        # Failure, we get 2 results!
        instance.entity.query = mock.MagicMock(return_value=[
            instance.entity('dcA', 'db1'),
            instance.entity('dcA', 'db2')
        ])
        self.assertRaises(ValueError, instance.get, 'db')
        instance.entity.query.assert_called_with({'datacenter': re.compile(r'^\w+$'),
                                                  'name': re.compile(r'^db$')})
        # No result => return None
        instance.entity.query = mock.MagicMock(return_value=[])
        self.assertIsNone(instance.get('db'))
        # Happy path
        instance.entity.query = mock.MagicMock(return_value=[instance.entity('dcA', 'db1')])
        self.assertEqual(instance.get('db1'), instance.entity('dcA', 'db1'))

    @mock.patch('conftool.extensions.dbconfig.entities.DbEditAction', autospec=True)
    def test_edit(self, dbedit):
        checker = mock.MagicMock()
        instance = Instance(self.schema, checker.check_instance)
        obj = instance.entity('dcA', 'db1')
        instance.get = mock.MagicMock(return_value=obj)
        self.assertEqual(instance.edit('db1'), (True, None))
        dbedit.assert_called_with(obj, checker.check_instance, Instance.example)
        # What if object doesn't exist
        instance.get = mock.MagicMock(return_value=None)
        obj = instance.entity('dcB', 'db4')
        self.assertEqual(
            instance.edit('db4'),
            (False, ['No instance found with name "db4"; please provide a datacenter'])
        )
        self.assertEqual(instance.edit('db4', 'dcB'), (True, None))
        dbedit.assert_called_with(obj, checker.check_instance, Instance.example)

    def _mock_object(self):
        checker = mock.MagicMock()
        instance = Instance(self.schema, checker)
        obj = instance.entity('dcA', 'db1')
        obj.host_ip = '192.168.0.2'
        obj.port = 3306
        obj.sections = {
            's1': {'pooled': True, 'weight': 10, 'percentage': 100},
            's2': {'pooled': True, 'weight': 0, 'percentage': 100},
        }
        obj.write = mock.MagicMock()
        return (instance, obj)

    def test_update(self):
        instance, obj = self._mock_object()
        # Let's assume a successful check.
        instance.checker.return_value = []
        mock_callback = mock.MagicMock()
        self.assertEqual(instance._update(obj, mock_callback, section=None, group=None), [])
        mock_callback.assert_has_calls([mock.call(obj, 's1', None),
                                        mock.call(obj, 's2', None)],
                                       any_order=True)
        # We actively ignore additional arguments
        instance._update(obj, mock_callback, section='s1', group='group', test=120)
        mock_callback.assert_called_with(obj, 's1', 'group')
        # Now error conditions:
        # 1 - callback fails
        mock_callback.side_effect = ValueError('FAIL!')
        self.assertEqual(instance._update(obj, mock_callback),
                         ['Callback failed!', 'FAIL!'])
        mock_callback.side_effect = None
        # 2 - trying to act on a section that's not present
        self.assertEqual(instance._update(obj, mock_callback, section='x44'),
                         ['Section "x44" is not configured for db1'])

    def test_depool(self):
        # Let's assume a successful check.
        instance, obj = self._mock_object()
        instance.checker.return_value = []

        # First case: no object
        instance.get = mock.MagicMock(return_value=None)
        self.assertEqual(instance.depool('db1'), (False, ['instance not found']))
        obj.write.assert_not_called()
        # Object present
        instance.get = mock.MagicMock(return_value=obj)
        self.assertEqual(instance.depool('db1', section='s1'), (True, None))
        self.assertFalse(obj.sections['s1']['pooled'])
        self.assertTrue(obj.sections['s2']['pooled'])
        assert obj.write.called
        # No section selected
        obj.write.reset_mock()
        self.assertEqual(instance.depool('db1'), (True, None))
        self.assertFalse(obj.sections['s2']['pooled'])
        assert obj.write.called
        # Bad params: no section, but group is passed
        obj.write.reset_mock()
        self.assertEqual(instance.depool('db3', None, 'vslow'),
                         (False, ['Cannot select a group but not a section']))
        obj.write.assert_not_called()
        # Let's try to depool a group, on an instance without groups
        self.assertEqual(instance.depool('db1', 's1', 'vslow'),
                         (False, ["No groups are configured for section 's1'"]))
        # Now let's test the happy path
        obj.sections['s1']['groups'] = {'vslow': {'pooled': True, 'weight': 10},
                                        'dump': {'pooled': True, 'weight': 10}}
        self.assertEqual(instance.depool('db1', 's1', 'vslow'), (True, None))
        self.assertFalse(obj.sections['s1']['groups']['vslow']['pooled'])
        self.assertTrue(obj.sections['s1']['groups']['dump']['pooled'])
        # Now the other option
        self.assertEqual(instance.depool('db1', 's1', 'foobar'),
                         (False, ['Group "foobar" is not configured in section "s1"']))
        # All groups alias
        self.assertEqual(instance.depool('db1', section='s1', group='all'), (True, None))
        self.assertFalse(obj.sections['s1']['groups']['vslow']['pooled'])
        self.assertFalse(obj.sections['s1']['groups']['dump']['pooled'])

    def test_pool(self):
        # This test is going to be simpler as it's basically the same as depooling with a twist
        # Let's assume a successful check.
        instance, obj = self._mock_object()
        instance.checker.return_value = []
        # Object present
        instance.get = mock.MagicMock(return_value=obj)
        # Let's first depool
        instance.depool('db1')
        obj.write.reset_mock()
        self.assertEqual(instance.pool('db1', section='s1'), (True, None))
        self.assertTrue(obj.sections['s1']['pooled'])
        self.assertFalse(obj.sections['s2']['pooled'])
        assert obj.write.called
        instance.pool('db1', percentage=10)
        self.assertTrue(obj.sections['s2']['pooled'])
        self.assertEqual(obj.sections['s1']['percentage'], 10)
        self.assertEqual(obj.sections['s2']['percentage'], 10)
        obj.sections['s1']['groups'] = {'vslow': {'pooled': False, 'weight': 10},
                                        'dump': {'pooled': False, 'weight': 10}}
        # Now let's test how if we select a group, percentage will remain the same
        self.assertEqual(instance.pool('db1', section='s1', group='vslow'), (True, None))
        self.assertEqual(obj.sections['s1']['percentage'], 10)
        self.assertTrue(obj.sections['s1']['groups']['vslow']['pooled'])
        self.assertFalse(obj.sections['s1']['groups']['dump']['pooled'])
        # All groups alias
        self.assertEqual(instance.pool('db1', section='s1', group='all'), (True, None))
        self.assertTrue(obj.sections['s1']['groups']['vslow']['pooled'])
        self.assertTrue(obj.sections['s1']['groups']['dump']['pooled'])
        # Setting a percentage when pooling a group is not supported
        obj.write.reset_mock()
        self.assertEqual(instance.pool('db1', section='s1', group='vslow', percentage=90),
                         (False, ['Percentages are only supported for global pooling']))
        obj.write.assert_not_called()

    def test_weight(self):
        # Let's assume a successful check.
        instance, obj = self._mock_object()
        instance.checker.check_instance.return_value = []
        # Object present
        instance.get = mock.MagicMock(return_value=obj)
        instance.weight('db1', 1)
        self.assertEqual(obj.sections['s1']['weight'], 1)
        self.assertEqual(obj.sections['s2']['weight'], 1)
        instance.weight('db1', 10, section='s1')
        self.assertEqual(obj.sections['s1']['weight'], 10)
        self.assertEqual(obj.sections['s2']['weight'], 1)
        obj.sections['s1']['groups'] = {'vslow': {'pooled': False, 'weight': 10},
                                        'dump': {'pooled': False, 'weight': 10}}
        instance.weight('db1', 0, section='s1', group='vslow')
        self.assertEqual(obj.sections['s1']['groups']['vslow']['weight'], 0)
        instance.weight('db1', 100, section='s1', group='all')
        self.assertEqual(obj.sections['s1']['groups']['vslow']['weight'], 100)
        self.assertEqual(obj.sections['s1']['groups']['dump']['weight'], 100)

    def test_check_state(self):
        # Try all cases.
        instance, _ = self._mock_object()

        # Case 1: no object

        self.assertEqual(instance._check_state(None), ['instance not found'])
        # Case 2: exception raised by validation
        obj = mock.MagicMock()
        obj.validate.side_effect = ValueError('test')
        self.assertEqual(instance._check_state(obj), ['test'])
        obj.validate.side_effect = None
        # Case 3: object uninitialized
        obj.sections = {}
        self.assertEqual(instance._check_state(obj), ['instance is uninitialized'])
        obj.sections = None
        self.assertEqual(instance._check_state(obj), None)

    def test_write_callback(self):
        instance, obj = self._mock_object()
        instance.get = mock.MagicMock(return_value=None)
        instance._update = mock.MagicMock(return_value=[])

        def cb(x):
            return x

        # Case 1: check_state returns an error
        self.assertEqual(instance.write_callback(cb, ('foo', )), (False, ['instance not found']))
        assert instance._update.call_count == 0
        instance.get.return_value = obj
        # Case 1: _update returns errors
        instance._update.return_value = ['test!']

        self.assertEqual(instance.write_callback(cb, ('foo', )), (False, ['test!']))
        instance._update.assert_called_with(obj, cb)
        instance._update.return_value = []
        # Case 5: _update works
        self.assertEqual(instance.write_callback(cb, ('foo', )), (True, None))
        assert obj.write.called
        # Case 6: Backend error is raised
        obj.write.side_effect = BackendError('Fail')
        self.assertEqual(instance.write_callback(cb, ('foo', )), (False, ['Fail']))
        # Case 7: generic exception is not catched
        obj.write.side_effect = ValueError('test')
        self.assertRaises(ValueError, instance.write_callback, cb, ('foo', ))


class TestDbSection(TestCase):

    def setUp(self):
        KVObject.backend = MockBackend({})
        KVObject.config = configuration.Config(driver="")
        self.schema = loader.Schema.from_file(
            os.path.join(test_base, 'fixtures', 'dbconfig', 'schema.yaml'))
        checker = mock.MagicMock()
        checker.return_value = []
        self.section = Section(self.schema, checker)
        obj = self.section.entity('extra', 'x1')
        obj.master = 'db1'
        obj.min_replicas = 3
        obj.write = mock.MagicMock()
        self.section.get = mock.MagicMock(return_value=obj)

    def test_set_master(self):
        obj = self.section.get('x1')
        self.assertEqual(self.section.set_master('x1', 'test', 'db2'), (True, None))
        self.assertEqual(obj.master, 'db2')
        self.section.get.assert_called_with('x1', 'test')
        obj.write.assert_called_with()

    def test_set_readonly(self):
        obj = self.section.get('x1', dc='dc3')
        self.section.set_readonly('x1', 'dc3', True, 'test')
        self.assertEqual(obj.ro_reason, 'test')
        self.assertTrue(obj.readonly)
        obj.write.assert_called_with()
        self.section.checker.assert_called_with(obj)

    def test_update(self):
        obj = self.section.get('x1')
        # Let's assume a successful check.
        mock_callback = mock.MagicMock()
        self.assertEqual(self.section._update(obj, mock_callback, a='b'), [])
        mock_callback.assert_called_with(obj)
        # Now error conditions:
        # 1 - callback fails
        mock_callback.side_effect = ValueError('FAIL!')
        self.assertEqual(self.section._update(obj, mock_callback),
                         ['Callback failed!', 'FAIL!'])


class TestDbConfig(TestCase):

    def setUp(self):
        KVObject.backend = MockBackend({})
        KVObject.config = configuration.Config(driver="")
        self.schema = loader.Schema.from_file(
            os.path.join(test_base, 'fixtures', 'dbconfig', 'schema.yaml'))
        self.instance = mock.MagicMock()
        self.section = mock.MagicMock()
        self.config = DbConfig(self.schema, self.instance, self.section)
        self.mwconfig = self.config.entity
        self.restore_path = os.path.join(test_base, 'fixtures', 'dbconfig', 'restore')

    def _mock_objects(self):
        db1 = self.schema.entities['dbconfig-instance']('test', 'db1')
        db1.sections = {
            's1': {'weight': 10, 'pooled': True, 'percentage': 50},
            's3': {'weight': 10, 'pooled': True, 'percentage': 100},
            's4': {'weight': 10, 'pooled': False, 'percentage': 100},
        }
        db2 = self.schema.entities['dbconfig-instance']('test', 'db2')
        db2.sections = {
            's3': {'weight': 10, 'pooled': True, 'percentage': 100},
            's4': {'weight': 10, 'pooled': True, 'percentage': 100},
        }
        db3 = self.schema.entities['dbconfig-instance']('test', 'db3')
        db3.sections = {
            's3': {'weight': 10, 'pooled': True, 'percentage': 100},
        }

        s1 = self.schema.entities['dbconfig-section']('test', 's1')
        s1.master = 'db1'
        s3 = self.schema.entities['dbconfig-section']('test', 's3')
        s3.master = 'db3'
        s3.readonly = True
        s3.ro_reason = 'Some reason.'
        s4 = self.schema.entities['dbconfig-section']('test', 's4')
        s4.master = 'db2'
        s4.min_replicas = 1
        return ([db1, db2, db3], [s1, s3, s4])

    def test_init(self):
        self.assertEqual(self.config.entity.__name__, 'Mwconfig')
        self.assertEqual(self.config.section, self.section)
        self.assertEqual(self.config.instance, self.instance)

    def test_live_config(self):
        self.mwconfig.query = mock.MagicMock()
        obj = self.mwconfig('eqiad', 'mwconfig')
        obj.val = {
            'readOnlyBySection': {},
            'sectionLoads': {'s1': [{'db1': 0}, {'db2': 10}], 'DEFAULT': [{'db3': 0}, {'db4': 10}]},
            'groupLoadsBySection': {'s1': {'vslow': {'db2': 10}, 'recentChanges': {'db14:3307': 4}}}
        }
        self.mwconfig.query.return_value = [obj]
        self.assertEqual(self.config.live_config['eqiad'], obj.val)
        self.mwconfig.query.assert_called_with({'name': re.compile('^dbconfig$')})

    def test_config_from_dbstore(self):
        self.config.compute_config = mock.MagicMock(return_value=[])
        self.assertEqual(self.config.config_from_dbstore, [])
        self.config.compute_config.assert_called_with(self.section.get_all.return_value,
                                                      self.instance.get_all.return_value)

    def test_compute_config(self):
        self.maxDiff = None
        instances, sections = self._mock_objects()
        expected = {
            'test':
            {'sectionLoads': {
                's1': [{'db1': 5}, {}],
                'DEFAULT': [{'db3': 10}, {'db1': 10, 'db2': 10}],
                's4': [{'db2': 10}, {}]},
             'groupLoadsBySection': {},
             'readOnlyBySection': {'s3': 'Some reason.'}}
        }
        res1 = self.config.compute_config(sections, instances)
        self.assertEqual(res1, expected)
        instances[1].sections['s3']['groups'] = {'vslow': {'weight': 1, 'pooled': True}}
        instances[1].percentage = 10
        # Let's check groups; first of all let's verify the weights honour the percentage
        res2 = self.config.compute_config(sections, instances)
        expected['test']['groupLoadsBySection']['DEFAULT'] = defaultdict(OrderedDict)
        expected['test']['groupLoadsBySection']['DEFAULT']['vslow']['db2'] = 1
        self.assertEqual(res2, expected)
        # Now let's check a globally non-pooled server doesn't get added to the groups
        instances[0].sections['s4']['groups'] = {'recentChanges': {'weight': 1, 'pooled': True}}
        self.assertEqual(self.config.compute_config(sections, instances), expected)
        # An instance that has section pooled: True but group pooled: False should appear in
        # sectionLoads but not groupLoadsBySection for that group.
        instances[1].sections['s3']['groups']['vslow']['pooled'] = False
        del expected['test']['groupLoadsBySection']['DEFAULT']
        self.assertEqual(self.config.compute_config(sections, instances), expected)

    def test_check_config(self):
        instances, sections = self._mock_objects()
        config = self.config.compute_config(sections, instances)
        self.assertEqual(
            self.config.check_config(config, sections),
            ['Section s4 is supposed to have minimum 1 replicas, found 0'])
        # Let's add one replica for s4. Config should be now ok
        config['test']['sectionLoads']['s4'][1]['db1'] = 1
        self.assertEqual(self.config.check_config(config, sections), [])
        # Let's remove the master from s3
        config['test']['sectionLoads']['DEFAULT'][0] = {}
        self.assertEqual(self.config.check_config(config, sections), ['Section s3 has no master'])
        # Let's try with two masters
        config['test']['sectionLoads']['DEFAULT'] = [{'db3': 0, 'db1': 5}, {}]
        self.assertEqual(self.config.check_config(config, sections),
                         ["Section s3 has multiple masters: ['db1', 'db3']"])
        # And now with a master that doesn't belong to the section
        config['test']['sectionLoads']['DEFAULT'] = [{'db4': 0}, {'db1': 5}]
        self.assertEqual(self.config.check_config(config, sections),
                         ['Section s3 is supposed to have master db3 but had db4 instead'])
        # Reset it to normal state
        config['test']['sectionLoads']['DEFAULT'] = [{'db3': 0}, {'db1': 5}]
        # Add an unknown section
        sections.pop()  # Will pop s4
        self.assertEqual(self.config.check_config(config, sections),
                         ['Section s4 is not configured'])

    def test_check_instance(self):
        instances, sections = self._mock_objects()
        self.config.instance.get_all.return_value = instances
        self.config.section.get_all.return_value = sections
        # Now let's reinstantiate the first instance, and pool it
        # in s4
        new_instances, _ = self._mock_objects()
        new_instances[0].sections['s4']['pooled'] = True
        self.assertEqual(self.config.check_instance(new_instances[0]), [])
        # Let's test if we re-pass the original instances
        self.assertEqual(self.config.check_instance(instances[0]),
                         ['Section s4 is supposed to have minimum 1 replicas, found 0'])

    def test_check_section(self):
        instances, sections = self._mock_objects()
        self.config.instance.get_all.return_value = instances
        self.config.section.get_all.return_value = sections
        # Let's test if we re-pass the original instances
        self.assertEqual(self.config.check_section(sections[2]),
                         ['Section s4 is supposed to have minimum 1 replicas, found 0'])

        # Now let's reduce the minimum number of replicas in s4
        _, new_sections = self._mock_objects()
        new_sections[2].min_replicas = 0
        self.assertEqual(self.config.check_section(new_sections[2]), [])

    def test_diff(self):
        instances, sections = self._mock_objects()
        a = self.config.compute_config(sections, instances)
        # Identical input should yield empty diff output.
        has_diff, diff = self.config.diff_configs(a, a)
        self.assertFalse(has_diff)
        self.assertEqual(list(diff), [])

        # Changing the weight of an instance should yield a diff.
        instances[1].sections['s3']['percentage'] = 10
        b = self.config.compute_config(sections, instances)
        has_diff, diff = self.config.diff_configs(a, b)
        diff = list(diff)
        self.assertTrue(has_diff)
        self.assertIn('+++ test/sectionLoads generated\n', diff)
        self.assertIn('-            "db2": 10\n', diff)
        self.assertIn('+            "db2": 1\n', diff)

    @mock.patch('builtins.open')
    @mock.patch('conftool.extensions.dbconfig.config.Path.mkdir')
    def test_commit(self, mocked_mkdir, mocked_open):
        instances, sections = self._mock_objects()
        self.config.instance.get_all.return_value = instances
        self.config.section.get_all.return_value = sections
        res = self.config.commit(batch=True)
        self.assertFalse(res.success)
        self.assertEqual(res.messages, ['Section s4 is supposed to have minimum 1 replicas, found 0'])

        instances[0].sections['s4']['pooled'] = True
        obj = mock.MagicMock()
        obj.name = 'mocked'
        self.config.entity = mock.MagicMock(return_value=obj)
        self.config.entity.config.cache_path = '/cache/path'
        res = self.config.commit(batch=True)
        self.assertTrue(res.success)
        self.assertRegexpMatches(res.messages[0],
                                 '^Previous configuration saved. To restore it run')
        self.assertRegexpMatches(mocked_open.call_args_list[0][0][0],
                                 '^/cache/path/dbconfig/[0-9-]{15}-.+.json')
        mocked_mkdir.assert_called_with(mode=0o755, parents=True)
        self.config.entity.assert_called_once_with('test', 'dbconfig')
        # Validation error is catched and an error is shown to the user
        obj.validate.side_effect = ValueError('test')
        res = self.config.commit(batch=True)
        self.assertFalse(res.success)
        self.assertEqual(res.messages[1:3], ['Object mocked failed to validate:', 'test'])

    @mock.patch('builtins.open')
    @mock.patch('conftool.extensions.dbconfig.config.Path.mkdir')
    def test_commit_fail_write_backup(self, mocked_mkdir, mocked_open):
        instances, sections = self._mock_objects()
        self.config.instance.get_all.return_value = instances
        self.config.section.get_all.return_value = sections
        instances[0].sections['s4']['pooled'] = True
        obj = mock.MagicMock()
        obj.name = 'mocked'
        self.config.entity = mock.MagicMock(return_value=obj)
        self.config.entity.config.cache_path = '/cache/path'
        mocked_open.side_effect = OSError
        res = self.config.commit(batch=True)
        self.assertTrue(res.success)
        self.assertRegexpMatches(res.messages[0],
                                 '^Unable to backup previous configuration. Failed to save it')

    def test_restore_valid(self):
        with open(os.path.join(self.restore_path, 'valid.json'), 'r') as f:
            res = self.config.restore(f)
        self.assertTrue(res.success)
        self.assertEqual(res.messages, [])

    def test_restore_valid_dc(self):
        with open(os.path.join(self.restore_path, 'invalid_data_multidc.json'), 'r') as f:
            res = self.config.restore(f, datacenter='dcA')
        self.assertTrue(res.success)
        self.assertEqual(res.messages, [])

    def test_restore_with_invalid_dc(self):
        with open(os.path.join(self.restore_path, 'invalid_data_multidc.json'), 'r') as f:
            res = self.config.restore(f, datacenter='dcB')
        self.assertFalse(res.success)
        self.assertEqual(res.messages,
                         ["Section s1 has multiple masters: ['dbb2:3307', 'dbb3']"])

    def test_restore_valid_with_missing_dc(self):
        with open(os.path.join(self.restore_path, 'invalid_data_multidc.json'), 'r') as f:
            res = self.config.restore(f, datacenter='invalid')
        self.assertFalse(res.success)
        self.assertEqual(res.messages,
                         ['Datacenter invalid not found in configuration to be restored'])

    def test_restore_invalid_json(self):
        with open(os.path.join(self.restore_path, 'invalid_json.json'), 'r') as f:
            res = self.config.restore(f)

        self.assertFalse(res.success)
        self.assertRegexpMatches(res.messages[0], r'^Invalid JSON configuration')

    def test_restore_invalid_data(self):
        with open(os.path.join(self.restore_path, 'invalid_data.json'), 'r') as f:
            res = self.config.restore(f)
        self.assertFalse(res.success)
        self.assertEqual(res.messages, ["Section s1 has multiple masters: ['dba2:3307', 'dba3']"])

    def test_restore_invalid_schema(self):
        with open(os.path.join(self.restore_path, 'invalid_schema.json'), 'r') as f:
            res = self.config.restore(f)

        self.assertFalse(res.success)
        self.assertEqual(res.messages[0], 'Object dbconfig failed to validate:')


class TestDbConfigCli(TestCase):

    def setUp(self):
        KVObject.backend = MockBackend({})
        KVObject.config = configuration.Config(driver="")
        self.schema_file = os.path.join(test_base, 'fixtures', 'dbconfig', 'schema.yaml')

    def get_cli(self, argv):
        args = dbconfig.parse_args(['--schema', self.schema_file] + argv)
        return DbConfigCli(args)

    def test_init(self):
        cli = self.get_cli(['instance', 'db1', 'get'])
        self.assertIsInstance(cli.db_config, DbConfig)
        self.assertIsInstance(cli.instance, Instance)
        self.assertIsInstance(cli.section, Section)

    def test_run_action(self):
        cli = self.get_cli(['instance', 'db1', 'get'])
        cli._run_on_instance = mock.MagicMock(return_value=ActionResult(True, 0))
        self.assertEqual(cli.run_action(), 0)
        assert cli._run_on_instance.called
        # Check section call, and what happens in a failure
        cli = self.get_cli(['section', 's1', 'ro', 'PANIC'])
        cli._run_on_section = mock.MagicMock(
            return_value=ActionResult(False, 1, messages=['test']))
        self.assertEqual(cli.run_action(), 1)
        assert cli._run_on_section.called
        # Finally, config
        cli = self.get_cli(['config', 'commit'])
        cli._run_on_config = mock.MagicMock(return_value=ActionResult(True, 0))
        self.assertEqual(cli.run_action(), 0)
        assert cli._run_on_config.called

    def test_run_on_instance(self):
        # Case 1: get
        cli = self.get_cli(['instance', 'db1', 'get'])
        cli.instance.get = mock.MagicMock(return_value=None)
        res = cli._run_on_instance()
        self.assertFalse(res.success)
        self.assertEqual(res.messages, ["DB instance 'db1' not found"])
        cli.instance.get.assert_called_with('db1', None)
        cli.instance.get.return_value = cli.instance.entity('test', 'db1')
        res = cli._run_on_instance()
        self.assertTrue(res.success)
        self.assertEqual(res.messages, [])
        cli.instance.get.side_effect = ValueError('test!')
        res = cli._run_on_instance()
        self.assertFalse(res.success)
        self.assertEqual(res.messages, ['Unexpected error:', 'test!'])
        # Get all instances
        cli = self.get_cli(['instance', 'all', 'get'])
        cli.instance.get_all = mock.MagicMock(return_value=iter(()))
        res = cli._run_on_instance()
        res = cli._run_on_instance()
        self.assertTrue(res.success)
        self.assertEqual(res.messages, [])
        cli.instance.get_all.return_value = iter(
            [cli.instance.entity('test', 'db1'), cli.instance.entity('test', 'db2')])
        res = cli._run_on_instance()
        self.assertTrue(res.success)
        self.assertEqual(res.messages, [])

        # Case 2: edit
        cli = self.get_cli(['instance', 'db1', 'edit'])
        cli.instance.edit = mock.MagicMock(return_value=(True, None))
        res = cli._run_on_instance()
        self.assertTrue(res.success)
        self.assertEqual(res.messages, [])
        cli.instance.edit.assert_called_with('db1', datacenter=None)
        # Case 3: pool
        cli = self.get_cli(['instance', 'db1', 'pool'])
        cli.instance.pool = mock.MagicMock(return_value=(True, None))
        res = cli._run_on_instance()
        self.assertTrue(res.success)
        self.assertEqual(res.messages, [])
        cli.instance.pool.assert_called_with('db1', None, None, None)
        cli = self.get_cli(['instance', 'db1', 'pool', '-p', '10',
                            '--section', 's1', '--group', 'vslow'])
        cli.instance.pool = mock.MagicMock(return_value=(True, None))
        res = cli._run_on_instance()
        self.assertTrue(res.success)
        self.assertEqual(res.messages, [])
        cli.instance.pool.assert_called_with('db1', 10, 's1', 'vslow')
        # Case 4: depool
        cli = self.get_cli(['instance', 'db1', 'depool',
                            '--section', 's1', '--group', 'vslow'])
        cli.instance.depool = mock.MagicMock(return_value=(True, None))
        res = cli._run_on_instance()
        self.assertTrue(res.success)
        self.assertEqual(res.messages, [])
        cli.instance.depool.assert_called_with('db1', 's1', 'vslow')
        cli = self.get_cli(['instance', 'db1', 'depool'])
        cli.instance.depool = mock.MagicMock(return_value=(True, None))
        res = cli._run_on_instance()
        self.assertTrue(res.success)
        self.assertEqual(res.messages, [])
        cli.instance.depool.assert_called_with('db1', None, None)
        cli = self.get_cli(['instance', 'db1', 'set-weight', '1', '--section', 's1'])
        cli.instance.weight = mock.MagicMock(return_value=(True, None))
        res = cli._run_on_instance()
        self.assertTrue(res.success)
        self.assertEqual(res.messages, [])
        cli.instance.weight.assert_called_with('db1', 1, 's1', None)

    def test_run_on_section(self):
        # Case 1: get
        cli = self.get_cli(['-s', 'test', 'section', 's1', 'get'])
        cli.section.get = mock.MagicMock(return_value=None)
        res = cli._run_on_section()
        self.assertFalse(res.success)
        self.assertEqual(res.messages, ["DB section 's1' not found"])
        cli.section.get.assert_called_with('s1', 'test')
        cli.section.get.return_value = cli.section.entity('test', 's1')
        res = cli._run_on_section()
        self.assertTrue(res.success)
        self.assertEqual(res.messages, [])
        cli.section.get.side_effect = ValueError('error')
        res = cli._run_on_section()
        self.assertFalse(res.success)
        self.assertEqual(res.messages, ['error'])

        cli = self.get_cli(['-s', 'test', 'section', 'all', 'get'])
        cli.section.get_all = mock.MagicMock(return_value=iter(()))
        res = cli._run_on_section()
        self.assertTrue(res.success)
        self.assertEqual(res.messages, [])
        cli.section.get_all.return_value = iter(
            [cli.section.entity('test', 's1'), cli.section.entity('test', 's2')])
        res = cli._run_on_section()
        self.assertTrue(res.success)
        self.assertEqual(res.messages, [])

        # Case 2: edit
        cli = self.get_cli(['-s', 'test', 'section', 's1', 'edit'])
        cli.section.edit = mock.MagicMock(return_value=(True, None))
        res = cli._run_on_section()
        self.assertTrue(res.success)
        self.assertEqual(res.messages, [])
        cli.section.edit.assert_called_with('s1', 'test')
        # Case 3: set-master
        cli = self.get_cli(['-s', 'test', 'section', 's1', 'set-master', 'db-test'])
        instance = cli.instance.entity('test', 'db-test')
        instance.sections['s1'] = {'weight': 100, 'pooled': True}
        cli.instance.get = mock.MagicMock(return_value=instance)
        cli.section.set_master = mock.MagicMock(return_value=(True, None))
        res = cli._run_on_section()
        self.assertTrue(res.success)
        self.assertEqual(res.messages, [])
        cli.instance.get.assert_called_with('db-test', dc='test')
        cli.section.set_master.assert_called_with('s1', 'test', 'db-test')
        # Case 4: ro/rw
        cli = self.get_cli(['-s', 'dc1', 'section', 's1', 'ro', 'test'])
        cli.section.set_readonly = mock.MagicMock(return_value=(True, None))
        res = cli._run_on_section()
        self.assertTrue(res.success)
        self.assertEqual(res.messages, [])
        cli.section.set_readonly.assert_called_with('s1', 'dc1', True, 'test')
        cli = self.get_cli(['-s', 'dc3', 'section', 's1', 'rw'])
        cli.section.set_readonly = mock.MagicMock(return_value=(True, None))
        res = cli._run_on_section()
        self.assertTrue(res.success)
        self.assertEqual(res.messages, [])
        cli.section.set_readonly.assert_called_with('s1', 'dc3', False)

    @mock.patch('conftool.extensions.dbconfig.config.DbConfig.live_config',
                new_callable=mock.PropertyMock)
    def test_run_on_config(self, mocked_live_config):
        mocked_live_config.return_value = {'dc1': {}}
        # Case 1: get
        cli = self.get_cli(['config', 'get'])
        res = cli._run_on_config()
        self.assertTrue(res.success)
        self.assertEqual(res.messages, [])
        assert mocked_live_config.called

        mocked_live_config.reset_mock()
        cli = self.get_cli(['-s', 'dc1', 'config', 'get'])
        res = cli._run_on_config()
        self.assertTrue(res.success)
        self.assertEqual(res.messages, [])
        assert mocked_live_config.called

        mocked_live_config.reset_mock()
        cli = self.get_cli(['-s', 'missing', 'config', 'get'])
        res = cli._run_on_config()
        self.assertFalse(res.success)
        self.assertEqual(res.messages, ['Datacenter missing not found in live configuration'])
        assert mocked_live_config.called

        mocked_live_config.reset_mock()
        cli = self.get_cli(['config', 'diff'])
        cli.db_config.compute_and_check_config = mock.MagicMock(return_value=({}, None))
        cli.db_config.diff_configs = mock.MagicMock(return_value=(False, iter(())))
        res = cli._run_on_config()
        self.assertTrue(res.success)
        self.assertEqual(res.messages, [])

        cli.db_config.compute_and_check_config = mock.MagicMock(return_value=({}, None))
        cli.db_config.diff_configs = mock.MagicMock(return_value=(True, iter(('diff'))))
        res = cli._run_on_config()
        self.assertTrue(res.success)
        self.assertEqual(res.exit_code, 1)
        self.assertEqual(res.messages, [])

        cli = self.get_cli(['-s', 'missing', 'config', 'diff'])
        cli.db_config.compute_and_check_config = mock.MagicMock(return_value=({}, None))
        cli.db_config.diff_configs = mock.MagicMock(return_value=(False, iter(())))
        res = cli._run_on_config()
        self.assertFalse(res.success)
        self.assertEqual(res.messages, ['Datacenter missing not found'])

        cli = self.get_cli(['config', 'commit'])
        cli.db_config.commit = mock.MagicMock(return_value=ActionResult(True, 0))
        res = cli._run_on_config()
        self.assertTrue(res.success)
        self.assertEqual(res.messages, [])
        cli.db_config.commit.assert_called_with(batch=False, datacenter=None)
