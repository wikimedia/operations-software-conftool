import os

from io import StringIO
from unittest.mock import patch

from conftool.cli import syncer
from conftool.tests.integration import IntegrationTestBase
from conftool.extensions import dbconfig


fixtures_base = os.path.realpath(
    os.path.join(os.path.dirname(__file__), os.path.pardir, "fixtures", "dbconfig")
)


class ConftoolTestCase(IntegrationTestBase):
    def setUp(self):
        self.schema_file = os.path.join(fixtures_base, "schema.yaml")

    def get_cli(self, *argv):
        args = dbconfig.parse_args(["--schema", self.schema_file] + list(argv))
        return dbconfig.DbConfigCli(args)

    def test_all_cycle(self):
        # Run a first sync
        sync = syncer.Syncer(self.schema_file, os.path.join(fixtures_base, "integration"))
        sync.load()
        # At this point, we don't have the mwconfig variables
        cli = self.get_cli("config", "get")
        self.assertEqual(cli.run_action(), 0)
        # Let's configure one section and one db
        s1 = cli.section.get("s1", "dcA")
        s1.master = "dba1"
        s1.min_replicas = 1
        s1.ro_reason = ""
        s1.write()
        dbA1 = cli.instance.get("dba1")
        dbA1.sections = {
            "s1": {"weight": 10, "pooled": True, "percentage": 50},
            "s3": {"weight": 10, "pooled": True, "percentage": 100},
            "s4": {"weight": 10, "pooled": False, "percentage": 100},
            "s10": {"weight": 0, "pooled": True, "percentage": 100},
        }
        dbA1.host_ip = "192.168.1.11"
        dbA1.port = 3306
        dbA1.write()
        # Now let's try to commit this config
        cli = self.get_cli("config", "commit", "--batch")
        # We won't be able to commit, as we don't have the minimum number of replicas
        self.assertEqual(cli.run_action(), 1)
        # Let's try to generate this config; similarly, this should return an error
        cli = self.get_cli("config", "generate")
        self.assertEqual(cli.run_action(), 1)
        # and same for diffing
        cli = self.get_cli("config", "diff")
        self.assertEqual(cli.run_action(), 3)
        # let's add a replica, with some groups too
        dbA2 = cli.instance.get("dba2")
        dbA2.sections = {
            "s1": {
                "weight": 10,
                "pooled": True,
                "percentage": 100,
                "groups": {"recentChanges": {"pooled": True, "weight": 1}},
            },
            "s3": {"weight": 10, "pooled": True, "percentage": 100},
            "s2": {"weight": 10, "pooled": True, "percentage": 100},
        }
        dbA2.host_ip = "192.168.1.12"
        dbA2.port = 3306
        dbA2.write()
        s2 = cli.section.get("s2", "dcA")
        s2.master = "dba2"
        s2.min_replicas = 0
        s2.ro_reason = ""
        s2.write()
        s10 = cli.section.get("s10", "dcA")
        s10.master = "dba1"
        s10.min_replicas = 0
        s10.ro_reason = ""
        s10.write()
        # Now generate and commit should work
        cli = self.get_cli("config", "generate")
        self.assertEqual(cli.run_action(), 0)
        # A batch commit without a message fails.
        cli = self.get_cli("config", "commit", "--batch")
        self.assertEqual(cli.run_action(), 4)
        cli = self.get_cli("config", "commit", "--batch", "--message", "initial commit")
        self.assertEqual(cli.run_action(), 0)
        # On empty diff exit early without committing or saving current configuration
        cli = self.get_cli("config", "commit")
        self.assertEqual(cli.run_action(), 0)
        # Limiting scope to a datacenter should work.
        cli = self.get_cli("-s", "dcA", "config", "generate")
        self.assertEqual(cli.run_action(), 0)
        cli = self.get_cli("-s", "dcA", "config", "diff")
        self.assertEqual(cli.run_action(), 0)
        cli = self.get_cli("-s", "dcA", "config", "commit")
        self.assertEqual(cli.run_action(), 0)
        # But limiting scope to a nonexistent datacenter should fail.
        cli = self.get_cli("-s", "nonexistent", "config", "generate")
        self.assertEqual(cli.run_action(), 2)
        cli = self.get_cli("-s", "nonexistent", "config", "diff")
        self.assertEqual(cli.run_action(), 2)
        cli = self.get_cli("-s", "nonexistent", "config", "commit")
        self.assertEqual(cli.run_action(), 2)
        # Let's make wikitech read-only; this should succeed.
        cli = self.get_cli("-s", "dcA", "section", "s10", "ro", "Maintenance")
        self.assertEqual(cli.run_action(), 0)
        cli = self.get_cli("config", "generate")
        self.assertEqual(cli.run_action(), 0)
        cli = self.get_cli(
            "config", "commit", "--batch", "--message", "wikitech ro for maintanance"
        )
        self.assertEqual(cli.run_action(), 0)
        # Let's verify that the live config contains s1
        lc = cli.db_config.live_config
        self.assertEqual(lc["dcA"]["sectionLoads"]["s1"], [{"dba1": 5}, {"dba2": 10}])
        # Let's try setting s2's master to dba1, which is not a replica of s2; this should fail.
        cli = self.get_cli("section", "s2", "set-master", "dba1")
        self.assertEqual(cli.run_action(), 3)
        # Let's try setting s2's master to a non-existent instance; this should fail.
        cli = self.get_cli("section", "s2", "set-master", "garbage1")
        self.assertEqual(cli.run_action(), 2)
        # Let's depool the master, this should be impossible and return false
        cli = self.get_cli("instance", "dba1", "depool")
        self.assertEqual(cli.run_action(), 1)
        dbA1 = cli.instance.get("dba1")
        self.assertTrue(dbA1.sections["s1"]["pooled"])
        # Now let's change master to dba2:33076, not before adding it
        dba21 = cli.instance.get("dba2:3307")
        dba21.sections = {
            "s1": {"weight": 0, "pooled": True, "percentage": 100},
            "s3": {"weight": 10, "pooled": True, "percentage": 100},
            "s2": {"weight": 10, "pooled": True, "percentage": 100},
        }
        dba21.host_ip = "192.168.1.12"
        dba21.port = 3307
        dba21.write()
        cli = self.get_cli("-s", "dcA", "section", "s1", "set-master", "dba2:3307")
        self.assertEqual(cli.run_action(), 0)
        # Do a cursory test of our diff we've built up.
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            cli = self.get_cli("config", "diff", "-u")
            self.assertEqual(cli.run_action(), 1)
            # We should see a diff header indicating changes in dcA/sectionLoads/s1
            self.assertRegex(mock_stdout.getvalue(), r"(?m)^\+\+\+ dcA/sectionLoads/s1 generated$")
            # and the addition of a 0 weight for the new master
            self.assertRegex(mock_stdout.getvalue(), r'(?m)^\+\s+ "dba2:3307": 0$')
            # and the addition of a 5 weight for the old master, with the trailing comma subtly
            # indicating it is no longer the master
            self.assertRegex(mock_stdout.getvalue(), r'(?m)^\+\s+ "dba1": 5,$')
        # Now we can depool dba1 safely
        cli = self.get_cli("instance", "dba1", "depool")
        self.assertEqual(cli.run_action(), 0)
        # And the config is valid again
        cli = self.get_cli("config", "commit", "--batch", "--message", "change master to dba2:3307")
        self.assertEqual(cli.run_action(), 0)
        # And no diff
        cli = self.get_cli("config", "diff")
        self.assertEqual(cli.run_action(), 0)
        # TODO: check that cached files are properly saved (issue with the tmpdir)
        lc = cli.db_config.live_config
        self.assertEqual(lc["dcA"]["sectionLoads"]["s1"], [{"dba2:3307": 0}, {"dba2": 10}])
        # Restore
        restore_file = os.path.join(fixtures_base, "restore", "valid.json")
        cli = self.get_cli("config", "restore", restore_file)
        self.assertEqual(cli.run_action(), 0)
