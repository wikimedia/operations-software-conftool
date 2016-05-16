import mock
import os
import unittest

from conftool import configuration, loader
from conftool.cli.syncer import Syncer, EntitySyncer
from conftool.tests.unit import MockBackend
from conftool.kvobject import KVObject

test_base = os.path.realpath(os.path.join(
    os.path.dirname(__file__), os.path.pardir))


class EntitySyncerTestCase(unittest.TestCase):
    def setUp(self):
        KVObject.backend = MockBackend({})
        KVObject.config = configuration.Config(driver="")
        self.fixtures_dir = os.path.join(test_base, 'fixtures')
        schema_file = os.path.join(self.fixtures_dir, 'schema.yaml')
        self.schema = loader.Schema.from_file(schema_file)
        self.es = EntitySyncer('unicorn', self.schema.entities['unicorn'])

    def test_init(self):
        # Test initialization
        e = EntitySyncer('unicorn', self.schema.entities['unicorn'])
        self.assertEquals(e.data, {})
        self.assertEquals(e.cls, self.schema.entities['unicorn'])

    def test_load_files(self):
        e = EntitySyncer('node', self.schema.entities['node'])
        # Test files with the wrong extensions do not get picked
        e.load_files(self.fixtures_dir)
        self.assertNotIn('eqiad/cache_text/https/not_to_load', e.data.keys())
        # Test actually loading data yields the expected result
        self.assertIn('eqiad/cache_text/https/cp1008', e.data.keys())
        # Test can survive a malformed file
        e = EntitySyncer('service', self.schema.entities['service'])
        e.load_files(self.fixtures_dir)
        # Test a malformed / empty file will cause removal _not_ to happen
        self.assertTrue(e.skip_removal)

    def test_get_changes(self):
        exp_data = {
            'dc1/clusterA/https/serv1': None,
            'dc1/clusterA/https/serv2': None,
            'dc1/clusterA/https/serv3': None,
        }
        current_data = {
            'dc1/clusterA/https/serv1': None,
            'dc1/clusterA/https/serv2': None,
            'dc1/clusterA/https/serv4': None,
            'dc1/clusterA/apache/serv3': None,
        }
        e = EntitySyncer('node', self.schema.entities['node'])
        # Test an empty remote means everything will be loaded
        KVObject.backend.driver.all_data = mock.Mock(
            side_effect=ValueError('Foo is not a directory'))
        to_add, to_remove = e.get_changes(exp_data)
        self.assertSetEqual(set(exp_data.keys()), to_add)
        # Test a different exception will be raised
        KVObject.backend.driver.all_data.side_effect = KeyError()
        self.assertRaises(KeyError, e.get_changes, exp_data)
        # Test all list are as expected
        KVObject.backend.driver.all_data = mock.Mock(
            return_value = current_data)
        to_add, to_remove = e.get_changes(exp_data)
        self.assertSetEqual(set(['dc1/clusterA/https/serv3']), to_add)
        self.assertSetEqual(set(['dc1/clusterA/https/serv4', 'dc1/clusterA/apache/serv3']),
                            to_remove)
        # Test an unmodified static value object will not get overwritten
        exp_data = {
            'clusterA/https': {
                'default_values': {'pooled': 'no', 'weight': 1},
                'datacenters': ['eqiad']
            },
            'clusterA/apache2': {
                'default_values': {'pooled': 'yes', 'weight': 1},
                'datacenters': ['eqiad']
            }
        }
        live_data = {
            'clusterA/https': {
                'default_values': {'pooled': 'no', 'weight': 1},
                'datacenters': ['eqiad']
            },
            'clusterA/apache2': {
                'default_values': {'pooled': 'no', 'weight': 1},
                'datacenters': ['eqiad']
            }
        }
        e = EntitySyncer('service', self.schema.entities['service'])
        KVObject.backend.driver.all_data = mock.Mock(
            return_value = live_data)
        to_add, to_remove = e.get_changes(exp_data)
        self.assertSetEqual(to_remove, set())
        self.assertSetEqual(to_add, set(['clusterA/apache2']))

    def test_load_cleanup(self):
        e = EntitySyncer('node', self.schema.entities['node'])
        e.get_changes = mock.Mock(
            return_value=(set(['dc1/clusterA/https/serv1', 'dc2/clusterB/https/serv2']),
                          set(['dc1/clusterA/https/serv2'])))
        obj   = mock.Mock()
        obj.exists = False
        obj.static_values = False
        e.cls = mock.Mock(return_value=obj)
        e.load()
        e.cls.assert_any_call('dc1', 'clusterA', 'https', 'serv1')
        e.cls.assert_any_call('dc2', 'clusterB', 'https', 'serv2')
        e.do_removal = True
        obj.exists = True
        e.cleanup()
        e.cls.assert_called_with('dc1', 'clusterA', 'https', 'serv2')
        obj.delete.assert_called_with()
        # Now let's test a static value object
        obj.static_values = True
        e.get_changes.return_value = (set(['dc1/clusterA/https/serv1']), set())
        e.data = {'dc1/clusterA/https/serv1': {'weight':2, 'pooled': 'yes'},
                  'dc2/clusterB/https/serv2': {'weight':2, 'pooled': 'yes'}}
        e.load()
        obj.from_net.assert_called_with(e.data['dc1/clusterA/https/serv1'])

class SyncerTestCase(unittest.TestCase):

    def setUp(self):
        KVObject.backend = MockBackend({})
        KVObject.config = configuration.Config(driver="")
        schema_file = os.path.join(test_base, 'fixtures', 'schema.yaml')
        self.fixtures_dir = os.path.join(test_base, 'fixtures')
        self.syncer = Syncer(schema_file, self.fixtures_dir)

    def test_simple_dependencies(self):
        # Test if no dependencies are present, add is always called at the top level
        self.syncer.add('pony', self.syncer.schema.entities['pony'])
        self.assertEqual(self.syncer.load_order, ['pony'])
        self.syncer.add('unicorn', self.syncer.schema.entities['unicorn'])
        self.assertEqual(self.syncer.load_order, ['pony', 'unicorn'])
        # If there is a dependency, the master class gets loaded first
        self.syncer.add('node', self.syncer.schema.entities['node'])
        self.assertEqual(self.syncer.load_order, ['pony', 'unicorn', 'service', 'node'])

    def test_loop_dependencies(self):
        self.syncer.schema.entities['pony'].depends = ['unicorn']
        self.syncer.schema.entities['unicorn'].depends = ['pony']
        # Test a circular dependency raises an exception
        with self.assertRaises(ValueError):
            self.syncer.add('pony', self.syncer.schema.entities['pony'])
        # A more complex example
        self.syncer.schema.entities['pony'].depends = ['node']
        self.syncer.schema.entities['service'].depends = ['unicorn']
        with self.assertRaises(ValueError):
            self.syncer.add('pony', self.syncer.schema.entities['pony'])

    def test_multiple_dependencies(self):
        self.syncer.schema.entities['pony'].depends = ['service']
        self.syncer.schema.entities['unicorn'].depends = ['service']
        self.syncer.schema.entities['service'].depends = []
        # Test multiple entities having the same dependency add it only once
        self.syncer.add('pony', self.syncer.schema.entities['pony'])
        self.syncer.add('unicorn', self.syncer.schema.entities['unicorn'])
        self.assertEqual(self.syncer.load_order, ['service', 'pony', 'unicorn'])

    def test_load(self):
        with mock.patch('conftool.cli.syncer.EntitySyncer') as mocker:
            obj = mock.Mock()
            mocker.return_value = obj
            self.syncer.load()
            for ent in ['unicorn', 'pony', 'service', 'node']:
                mocker.assert_any_call(ent, self.syncer.schema.entities[ent])
            obj.load_files.assert_called_with(self.fixtures_dir)
            obj.load.assert_called_with()

    def test_load_broken_schema(self):
        """
        Test `cli.syncer.Syncer.load` doesn't work if the schema is broken
        """
        schema_file = os.path.join(test_base, 'fixtures', 'broken_schema.yaml')
        syncer = Syncer(schema_file, self.fixtures_dir)
        self.assertTrue(syncer.schema.has_errors)
        with mock.patch('conftool.cli.syncer.EntitySyncer') as mocker:
            obj = mock.Mock()
            mocker.return_value = obj
            self.assertRaises(ValueError, syncer.load)
