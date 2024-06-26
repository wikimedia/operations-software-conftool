import argparse
import json
import os
import re
import shutil
import tempfile
from io import StringIO
from unittest.mock import patch

import pytest
import yaml
from conftool.extensions import reqconfig
from conftool.tests.integration import IntegrationTestBase

fixtures_base = os.path.realpath(
    os.path.join(os.path.dirname(__file__), os.path.pardir, "fixtures", "reqconfig")
)
STEP0_PATH = os.path.join(fixtures_base, "step0")


class ReqConfigTestBase(IntegrationTestBase):
    """Test requestctl base."""

    @classmethod
    def setUpClass(cls):
        """method to run before the test suite runs."""
        super().setUpClass()
        cls.schema = reqconfig.get_schema(cls.get_config())

    def get_cli(self, *argv):
        """Get a requestctl instance from args."""
        args = reqconfig.parse_args(argv)
        return reqconfig.cli.Requestctl(args)

    def get(self, what, *tags):
        """Get a conftool object."""
        return self.schema.entities[what](*tags)


class ReqConfigTest(ReqConfigTestBase):
    """Test requestctl."""

    def setUp(self):
        """Method run before every test."""
        super().setUp()
        # Run sync.
        for what in reversed(reqconfig.SYNC_ENTITIES):
            self.get_cli("sync", "-g", STEP0_PATH, what).run()

    # Required as long as this class inherits from TestCase
    @pytest.fixture(autouse=True)
    def capsys(self, capsys):
        self.capsys = capsys

    def test_sync_all(self):
        """Test syncing all properties."""
        # Now let's verify sync actually works.
        # We should have two actions defined now.
        all_actions = list(self.schema.entities["action"].query({"name": re.compile(".*")}))
        assert len(all_actions) == 3
        # These actions are not enabled, even if they are on disk.
        for obj in all_actions:
            assert obj.enabled is False
        # Enable one
        self.get_cli("enable", "cache-text/requests_ua_api").run()
        assert self.get("action", "cache-text", "requests_ua_api").enabled is True
        # And disable it.
        self.get_cli("disable", "cache-text/requests_ua_api").run()
        assert self.get("action", "cache-text", "requests_ua_api").enabled is False
        # Now let's try to sync actions, by adding a new one that has a bad expression
        bad_expr_path = os.path.join(fixtures_base, "bad_expr")
        # This should not explode, but still not add the object
        self.assertRaises(
            reqconfig.cli.RequestctlError,
            self.get_cli("sync", "-g", bad_expr_path, "action").run,
        )
        assert self.get("action", "cache-upload", "requests_ua_api").exists is False
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
        assert self.get("pattern", "cache-text", "restbase").exists is True
        # ok, let's retry with the expression fixed as well.
        step2_path = os.path.join(fixtures_base, "step2")
        for what in reqconfig.SYNC_ENTITIES:
            self.get_cli("sync", "-g", step2_path, "--purge", what).run()
        assert self.get("pattern", "cache-text", "restbase").exists is False

    def test_get(self):
        """Test requestctl get."""
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
        """Test some failure mode for bad args."""
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
        """Test requestctl dump."""
        tmpdir = tempfile.mkdtemp()
        try:
            for what in reversed(reqconfig.SYNC_ENTITIES):
                self.get_cli("dump", "-g", tmpdir, what).run()
                # Loading from the just-dumped dir should work.
                self.get_cli("sync", "-g", tmpdir, what).run()
        finally:
            shutil.rmtree(tmpdir)

    def test_log(self):
        """Test the behaviour of requestctl log."""
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            self.get_cli("log", "cache-text/enwiki_api_cloud").run()
        log_out = mock_stdout.getvalue()
        # Check url matching
        self.assertRegex(
            log_out,
            r'(?m)\(\s*ReqURL ~ "/w/api.php" or ReqURL ~ "\^/api/rest_v1/"\s*\)',
        )
        self.assertRegex(log_out, r'(?m)ReqHeader:X-Public-Cloud ~ "\^aws\$"')

    def test_vcl(self):
        """Test the behaviour of requestctl vcl."""
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            self.get_cli("vcl", "cache-text/enwiki_api_cloud").run()
        vcl = mock_stdout.getvalue()
        self.assertRegex(vcl, r"(?m)sudo requestctl disable 'cache-text/enwiki_api_cloud'")
        self.assertRegex(vcl, r'(?m)\(req.url ~ "/w/api.php" \|\| req.url ~ "\^/api/rest_v1/"\)')
        self.assertRegex(vcl, r'(?m)req.http.X-Public-Cloud ~ "\^azure\$"')
        self.assertRegex(
            vcl,
            r'(?m)vsthrottle\.is_denied\("requestctl:enwiki_api_cloud", 5000, 30s, 300s\)',
        )
        self.assertRegex(
            vcl,
            r'(?m)set req\.http\.X-Requestctl = req\.http\.X-Requestctl \+ ",enwiki_api_cloud"',
        )
        self.assertRegex(vcl, r"(?m) set req\.http\.Retry-After = 300;")
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            self.get_cli("vcl", "cache-text/bad_param_q").run()
        rule = mock_stdout.getvalue()
        assert rule.find('req.url ~ "[?&]q=\\w{12}" || req.method == "POST"') >= 0

    def test_commit(self):
        """Test the behaviour of requestctl commit."""
        # Test 1: enable a rule, commit, it should add the rule in the right place
        self.get_cli("enable", "cache-text/enwiki_api_cloud").run()
        self.get_cli("commit", "-b").run()
        global_vcl = self.schema.entities["vcl"]("cache-text", "global")
        assert global_vcl.exists
        # just to check it contains the rule we've just enabled.
        self.assertRegex(global_vcl.vcl, r'(?m)req.http.X-Public-Cloud ~ "\^azure\$"')
        # check rules for logging requests that have log_matching true
        dc1_vcl = self.schema.entities["vcl"]("cache-text", "dc1")
        self.assertRegex(
            dc1_vcl.vcl,
            r'(?m)set req\.http\.X-Requestctl = req\.http\.X-Requestctl \+ ",requests_ua_api"',
        )
        # Test 2: enable a second rule, disable the first (applied to different contexts), and the first vanishes the second is there.
        self.get_cli("disable", "cache-text/enwiki_api_cloud").run()
        self.get_cli("enable", "cache-text/requests_ua_api").run()
        self.get_cli("commit", "-b").run()
        global_vcl = self.schema.entities["vcl"]("cache-text", "global")
        for dc in ["dc1", "dc2"]:
            dc_vcl = self.schema.entities["vcl"]("cache-text", dc)
            self.assertRegex(dc_vcl.vcl, r"(?m)requests")
        assert global_vcl.vcl == ""

    def test_commit_preserve_ordering(self):
        """Test that requestctl commit preserves order."""
        # Let's enable 2 rules in the same context, check that multiple commits won't change the output
        self.get_cli("enable", "cache-text/enwiki_api_cloud").run()
        self.get_cli("enable", "cache-text/bad_param_q").run()
        self.get_cli("commit", "-b").run()
        global_vcl = self.schema.entities["vcl"]("cache-text", "global")
        for _ in range(10):
            self.get_cli("commit", "-b").run()
            assert global_vcl.vcl == self.schema.entities["vcl"]("cache-text", "global").vcl

    def test_find(self):
        """Test finding objects"""
        no_data = self.get_cli("find", "enwiki_api_cloud")
        one_match = self.get_cli("find", "cloud/ovh")
        multi_match = self.get_cli("find", "cache-text/action_api")
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            no_data.run()
            assert mock_stdout.getvalue() == "No entries found.\n"
            mock_stdout.truncate(0)
            one_match.run()
            assert mock_stdout.getvalue().endswith(
                "action: cache-text/enwiki_api_cloud, expression: ( pattern@cache-text/action_api OR pattern@cache-text/restbase ) AND ( ipblock@cloud/aws OR ipblock@cloud/azure OR ipblock@cloud/ovh )\n"
            )
            mock_stdout.truncate(0)
            multi_match.run()
            assert len(mock_stdout.getvalue().splitlines()) == 2

    # Can't use @pytest.mark.parametrize because subclass of TestCase
    def test_find_ip_ok(self):
        """It should find all the IP blocks the given IP is part of."""
        self.get_cli("find-ip", "-g", STEP0_PATH, "1.123.123.123").run()
        out, _ = self.capsys.readouterr()
        assert "IP 1.123.123.123 is part of prefix 1.0.0.0/8 in ipblock cloud/aws" == out.strip()

    # Can't use @pytest.mark.parametrize because subclass of TestCase
    def test_find_ip_missing(self):
        """It should tell that the given IP is not part of any IP block."""
        self.get_cli("find-ip", "-g", STEP0_PATH, "127.0.0.1").run()
        out, _ = self.capsys.readouterr()
        assert "IP 127.0.0.1 is not part of any ipblock on disk" == out.strip()

    def test_test_validate_bad_ip(self):
        bad_ip_path = os.path.join(fixtures_base, "bad_ip")
        self.get_cli("--debug", "sync", "--purge", "-g", bad_ip_path, "ipblock").run()
        # ensure we can load good addresses

        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            self.get_cli("get", "ipblock", "cloud/invalid", "-o", "yaml").run()
        data = yaml.safe_load(mock_stdout.getvalue())
        # The following should all be removed
        # ['not an ip address', '1.1.1.1.1', 2001::db8::1']

        self.assertEqual(data["cloud/invalid"]["cidrs"], ["1.1.1.1", "2.2.2.2/8", "2001:db8::1"])


class ReqConfigTestNoSync(ReqConfigTestBase):
    def test_validate(self):
        # Step 0 should verify without issues.
        self.get_cli("validate", STEP0_PATH).run()
        # Now let's try the step1, where we were removing an object that we needed:
        bad_expr_path = os.path.join(fixtures_base, "step1")
        with self.assertRaises(reqconfig.cli.RequestctlError):
            self.get_cli("validate", bad_expr_path).run()
