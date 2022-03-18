import argparse
import json
import os
import re
import shutil
import tempfile
from io import StringIO
from unittest.mock import patch

import yaml
from conftool.extensions import reqconfig
from conftool.tests.integration import IntegrationTestBase

fixtures_base = os.path.realpath(
    os.path.join(os.path.dirname(__file__), os.path.pardir, "fixtures", "reqconfig")
)


class ReqConfigTest(IntegrationTestBase):
    @classmethod
    def setUpClass(cls):
        """method to run before every test."""
        super().setUpClass()
        cls.schema = reqconfig.get_schema(cls.get_config())

    def setUp(self):
        super().setUp()
        # Run sync.
        step0_path = os.path.join(fixtures_base, "step0")
        for what in reqconfig.cli.SCHEMA:
            self.get_cli("sync", "-g", step0_path, what).run()

    def get_cli(self, *argv):
        args = reqconfig.parse_args(argv)
        return reqconfig.cli.Requestctl(args)

    def get(self, what, *tags):
        return self.schema.entities[what](*tags)

    def test_sync_all(self):
        # Now let's verify sync actually works.
        # We should have two actions defined now.
        all_actions = list(
            self.schema.entities["action"].query({"name": re.compile(".*")})
        )
        assert len(all_actions) == 2
        # These actions are not enabled, even if they are on disk.
        for obj in all_actions:
            assert obj.enabled == False
        # Enable one
        self.get_cli("enable", "cache-text/requests_ua_api").run()
        assert self.get("action", "cache-text", "requests_ua_api").enabled == True
        # And disable it.
        self.get_cli("disable", "cache-text/requests_ua_api").run()
        assert self.get("action", "cache-text", "requests_ua_api").enabled == False
        # Now let's try to sync actions, by adding a new one that has a bad expression
        bad_expr_path = os.path.join(fixtures_base, "bad_expr")
        # This should not explode, but still not add the object
        self.assertRaises(
            reqconfig.cli.RequestctlError,
            self.get_cli("sync", "-g", bad_expr_path, "action").run,
        )
        assert self.get("action", "cache-upload", "requests_ua_api").exists == False
        # Now let's try to sync again, this time with --purge, in a dir where we removed
        # one pattern.
        # Interestingly, this pattern removal will make one of the actions invalid.
        # So we should actually NOT remove the pattern
        step1_path = os.path.join(fixtures_base, "step1")
        # Running with --debug doesn't change anything in tests but allows us to verify it's
        # accepted.
        self.assertRaises(
            reqconfig.cli.RequestctlError,
            self.get_cli("--debug", "sync", "-g", step1_path, "--purge", "pattern").run,
        )
        assert self.get("pattern", "cache-text", "restbase").exists == True
        # ok, let's retry with the expression fixed as well.
        step2_path = os.path.join(fixtures_base, "step2")
        for what in sorted(reqconfig.cli.SCHEMA):
            self.get_cli("sync", "-g", step2_path, "--purge", what).run()
        assert self.get("pattern", "cache-text", "restbase").exists == False

    def test_get(self):
        # Get a specific pattern
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            self.get_cli("get", "pattern", "cache-text/action_api", "-o", "json").run()
        json.loads(mock_stdout.getvalue())
        # now an ipblock, yaml format
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            self.get_cli("get", "ipblock", "cloud/aws", "-o", "yaml").run()
        yaml.safe_load(mock_stdout)
        # finally list all actions, pretty printed
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            self.get_cli("get", "action").run()
        self.assertRegex(mock_stdout.getvalue(), r"cache-text/requests_ua_api")
        self.assertRegex(mock_stdout.getvalue(), r"cache-text/enwiki_api_cloud")
        # get with a badly formatted path will result in an exception
        self.assertRaises(
            reqconfig.cli.RequestctlError,
            self.get_cli("get", "ipblock", "cloud-aws", "-o", "yaml").run,
        )
        # On the other hand if we're not finding anything, we return an empty dictionary.
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            self.get_cli("get", "ipblock", "cloud/not-existent", "-o", "yaml").run()
        self.assertEqual(yaml.safe_load(mock_stdout.getvalue()), {})

    def test_failures(self):
        args = [
            {"command": "unicorn", "action": "pink"},  # inexistent command
            {
                "command": "enable",
                "action": "something/not-here",
            },  # enable a non existent action.
        ]
        for test_case in args:
            test_case.update({"debug": False, "config": None, "object_type": "action"})
            args = argparse.Namespace(**test_case)
            rq = reqconfig.cli.Requestctl(args)
            self.assertRaises(reqconfig.cli.RequestctlError, rq.run)

    def test_dump(self):
        tmpdir = tempfile.mkdtemp()
        try:
            for what in reqconfig.cli.SCHEMA:
                self.get_cli("dump", "-g", tmpdir, what).run()
                # Loading from the just-dumped dir should work.
                self.get_cli("sync", "-g", tmpdir, what).run()
        finally:
            shutil.rmtree(tmpdir)
