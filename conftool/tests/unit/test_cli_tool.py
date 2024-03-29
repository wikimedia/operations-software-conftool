import argparse
import sys

from unittest import mock, TestCase

from conftool.kvobject import KVObject
from conftool import configuration
from conftool import node
from conftool.tests.unit import MockBackend
from conftool.cli import tool


class TestToolCli(TestCase):
    def setUp(self):
        KVObject.backend = MockBackend({})
        KVObject.config = configuration.Config(driver="")

    def _mock_list(self, values):
        KVObject.backend.driver.ls = mock.MagicMock(return_value=values)

    def _mock_args(self, **kw):
        arg = mock.MagicMock()
        arg.object_type = "node"
        arg.mode = "tags"
        arg.schema = "conftool/tests/fixtures/schema.yaml"
        arg.config = "conftool/tests/fixtures/config.yaml"
        for prop, value in kw.items():
            setattr(arg, prop, value)
        return arg

    def test_init(self):
        """Test case for `conftool.cli.tool.ToolCli.__init__`"""
        args = self._mock_args(taglist="")
        with self.assertRaises(SystemExit) as cm:
            t = tool.ToolCli(args)
            t.tags
        self.assertEqual(cm.exception.code, 1)

        args = self._mock_args(taglist="a=b,b=c,d=2")
        t = tool.ToolCli(args)
        self.assertEqual(t.args.mode, "tags")
        self.assertCountEqual(t._tags, ["a=b", "b=c", "d=2"])

    def test_tags(self):
        args = self._mock_args(taglist="dc=a,cluster=b,service=apache2")
        t = tool.ToolCli(args)
        self.assertCountEqual(t.tags, ["a", "b", "apache2"])

    def test_hosts_list_tags(self):
        """Tests getting the host list"""
        host_dir = [
            ("cp1011.example.com", {"pooled": "yes"}),
            ("cp1020.example.com", {"pooled": "no"}),
            ("cp1014.local", {"pooled": "no"}),
        ]
        self._mock_list(host_dir)
        args = self._mock_args(taglist="dc=a,cluster=b,service=apache2")

        def tagged(args, name, act):
            t = tool.ToolCli(args)
            t._namedef = name
            t._action = act
            return [el for el in t._tagged_host_list()]

        # Getting a single node
        elements = tagged(args, "a_node_name", "get")
        self.assertEqual(elements, ["a_node_name"])

        # Getting all nodes
        elements = tagged(args, "all", "dummy")
        self.assertCountEqual(elements, [k for (k, v) in host_dir])

        # GET of all nodes is a special case
        elements = tagged(args, "all", "get")
        self.assertEqual(elements, [])

        # Regex matching
        elements = tagged(args, r"re:.*\.local", "get")
        self.assertEqual(elements, ["cp1014.local"])

        # All nodes set raise a system exit
        with self.assertRaises(SystemExit):
            tagged(args, "all", "set")

        # Majority of nodes via a regex will raise a system exit
        with self.assertRaises(SystemExit):
            tagged(args, r"re:cp10(11|20)\.example\.com", "set")

    def test_host_multiple_services(self):
        """Set all services in a single host w/ and w/o the --host flag"""
        # The query return a single host with multiple services
        query_result = [
            node.Node("dc", "cluster", "service_a", "host_a"),
            node.Node("dc", "cluster", "service_b", "host_a"),
            node.Node("dc", "cluster", "service_c", "host_a"),
        ]

        args = self._mock_args(selector="name=cp3009.esams.wmnet", host=False)
        cli = tool.ToolCliByLabel(args)
        cli._action = "set"
        cli.entity.query = mock.MagicMock(return_value=query_result)

        # With args.host=False we expect input question, answering yes
        with mock.patch("builtins.input", return_value="y") as _raw:
            cli.host_list()
            _raw.assert_called_once_with("confctl>")

        # With args.host=False we expect input question, answering no
        with mock.patch("builtins.input", return_value="n") as _raw:
            self.assertRaises(SystemExit, cli.host_list)

        # With args.host=True we do not expect input questions
        cli.args.host = True
        with mock.patch("builtins.input") as _raw:
            cli.host_list()
            self.assertEqual(_raw.call_args_list, [])

        # Adding another host to the query result
        query_result.append(node.Node("dc", "cluster", "service_a", "host_b"))
        cli.entity.query = mock.MagicMock(return_value=query_result)

        # With args.host=True we expect input question, answering y
        with mock.patch("builtins.input", return_value="y") as _raw:
            cli.host_list()
            _raw.assert_called_once_with("confctl>")

    def test_parse_args(self):
        # Taglist
        cmdline = ["tags", "dc=a,cluster=b", "--action", "get", "all"]
        args = tool.parse_args(cmdline)
        self.assertEqual(args.mode, "tags")
        self.assertEqual(args.taglist, "dc=a,cluster=b")
        self.assertEqual(args.action, [["get", "all"]])
        # Check the subparser command is required
        self.assertRaises(SystemExit, tool.parse_args, [])
        cmdline = ["pool"]
        with mock.patch("conftool.cli.tool.socket.getfqdn") as mocker:
            mocker.return_value = "FooBar"
            args = tool.parse_args(cmdline)
            self.assertEqual(args.hostname, "FooBar")
            cmdline = ["pool", "--hostname", "pink.unicorn"]
            args = tool.parse_args(cmdline)
            self.assertEqual(args.hostname, "pink.unicorn")


class TestToolCliSimpleAction(TestCase):
    def setUp(self):
        KVObject.backend = MockBackend({})
        KVObject.config = configuration.Config(driver="")

    def _args(self):
        args = argparse.Namespace()
        args.mode = "pool"
        args.hostname = "foobar"
        args.debug = False
        args.object_type = "node"
        args.schema = "/nonexistent"
        args.config = "conftool/tests/fixtures/config.yaml"
        return args

    def test_init(self):
        args = self._args()
        t = tool.ToolCliSimpleAction(args)
        self.assertEqual(t.args.selector, "name=foobar")
        self.assertEqual(t.args.action, ["set/pooled=yes"])
        args = self._args()
        args.service = "Foo"
        t = tool.ToolCliSimpleAction(args)
        self.assertEqual(t.args.selector, "name=foobar,service=Foo")
        args = self._args()
        args.object_type = "service"
        self.assertRaises(SystemExit, tool.ToolCliSimpleAction, args)

    def test_host_list(self):
        mock_list = []
        for i in range(10):
            mock_list.append(node.Node("dcA", "clusterA", "service{}".format(i), "foobar"))
        args = self._args()
        t = tool.ToolCliSimpleAction(args)
        t.entity.query = mock.MagicMock(return_value=mock_list)
        self.assertEqual(t.host_list(), mock_list)
