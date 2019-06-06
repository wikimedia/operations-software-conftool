import os

from conftool.cli import syncer
from conftool.tests.integration import IntegrationTestBase
from conftool.extensions import dbconfig


fixtures_base = os.path.realpath(os.path.join(
    os.path.dirname(__file__), os.path.pardir, 'fixtures', 'dbconfig'))


class ConftoolTestCase(IntegrationTestBase):

    def setUp(self):
        self.schema_file = os.path.join(fixtures_base, 'schema.yaml')

    def get_cli(self, *argv):
        args = dbconfig.parse_args(['--schema', self.schema_file] + list(argv))
        return dbconfig.DbConfigCli(args)

    def test_all_cycle(self):
        # Run a first sync
        sync = syncer.Syncer(
            self.schema_file,
            os.path.join(fixtures_base, 'integration')
        )
        sync.load()
        # At this point, we don't have the mwconfig variables
        cli = self.get_cli('config', 'get')
        self.assertEqual(cli.run_action(), True)
        # Let's configure one section and one db
        s1 = cli.section.get('s1', 'dcA')
        s1.master = 'dba1'
        s1.min_slaves = 1
        s1.reason = ''
        s1.write()
        dbA1 = cli.instance.get('dba1')
        dbA1.hostname = 'dbA1.example.com'
        dbA1.sections = {
            's1': {'weight': 10, 'pooled': True, 'percentage': 50},
            's3': {'weight': 10, 'pooled': True, 'percentage': 100},
            's4': {'weight': 10, 'pooled': False, 'percentage': 100},
        }
        dbA1.host_ip = '192.168.1.11'
        dbA1.port = 3306
        dbA1.write()
        # Now let's try to commit this config
        cli = self.get_cli('config', 'commit')
        # We won't be able to commit, as we don't have the minimum number of slaves
        self.assertEqual(cli.run_action(), False)
        # let's add a slave, with some groups too
        dbA2 = cli.instance.get('dba2')
        dbA2.hostname = 'dbA2.example.com'
        dbA2.sections = {
            's1': {'weight': 10, 'pooled': True, 'percentage': 100,
                   'groups': {'recentChanges': {'pooled': True, 'weight': 1}}},
            's3': {'weight': 10, 'pooled': True, 'percentage': 100},
            's2': {'weight': 10, 'pooled': True, 'percentage': 100},
        }
        dbA2.host_ip = '192.168.1.12'
        dbA2.port = 3306
        dbA2.write()
        s2 = cli.section.get('s2', 'dcA')
        s2.master = 'dba2'
        s2.min_slaves = 0
        s2.reason = ''
        s2.write()
        # Now it should work
        self.assertEqual(cli.run_action(), True)
        # Let's verify that the live config contains s1
        lc = cli.db_config.live_config
        self.assertEqual(lc['dcA']['sectionLoads']['s1'], [{'dba1': 5}, {'dba2': 10}])
        # Let's try setting s2's master to dba1, which is not a replica of s2; this should fail.
        cli = self.get_cli('section', 's2', 'set-master', 'dba1')
        self.assertEqual(cli.run_action(), False)
        # Let's try setting s2's master to a non-existent instance; this should fail.
        cli = self.get_cli('section', 's2', 'set-master', 'garbage1')
        self.assertEqual(cli.run_action(), False)
        # Let's depool the master, this should be impossible and return false
        cli = self.get_cli('instance', 'dba1', 'depool')
        self.assertEqual(cli.run_action(), False)
        dbA1 = cli.instance.get('dba1')
        self.assertTrue(dbA1.sections['s1']['pooled'])
        # Now let's change master to dba2:33076, not before adding it
        dba21 = cli.instance.get('dba2:3307')
        dba21.hostname = 'dbA2.example.com'
        dba21.sections = {
            's1': {'weight': 0, 'pooled': True, 'percentage': 100},
            's3': {'weight': 10, 'pooled': True, 'percentage': 100},
            's2': {'weight': 10, 'pooled': True, 'percentage': 100},
        }
        dba21.host_ip = '192.168.1.12'
        dba21.port = 3307
        dba21.write()
        cli = self.get_cli('-s', 'dcA', 'section', 's1', 'set-master', 'dba2:3307')
        self.assertEqual(cli.run_action(), True)
        # Now we can depool dba1 safely
        cli = self.get_cli('instance', 'dba1', 'depool')
        self.assertEqual(cli.run_action(), True)
        # And the config is valid again
        cli = self.get_cli('config', 'commit')
        self.assertEqual(cli.run_action(), True)
        # TODO: check that cached files are properly saved (issue with the tmpdir)
        lc = cli.db_config.live_config
        self.assertEqual(lc['dcA']['sectionLoads']['s1'], [{'dba2:3307': 0}, {'dba2': 10}])
