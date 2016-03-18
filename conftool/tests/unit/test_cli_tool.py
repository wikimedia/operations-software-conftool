import unittest
import mock
from conftool.kvobject import KVObject
from conftool import configuration
from conftool import node
from conftool.tests.unit import MockBackend
from conftool.cli import tool


class TestToolCli(unittest.TestCase):

    def setUp(self):
        KVObject.backend = MockBackend({})
        KVObject.config = configuration.Config(driver="")

    def _mock_list(self, values):
        KVObject.backend.driver.ls = mock.MagicMock(return_value=values)

    def _mock_args(self, **kw):
        arg = mock.MagicMock()
        arg.object_type = 'node'
        arg.mode = 'tags'
        for prop, value in kw.items():
            setattr(arg, prop, value)
        return arg

    def test_init(self):
        """Test case for `conftool.cli.tool.ToolCli.__init__`"""
        args = self._mock_args(taglist="")
        with self.assertRaises(SystemExit) as cm:
            t = tool.ToolCli(args)
            t.tags
        self.assertEquals(cm.exception.code, 1)

        args = self._mock_args(taglist="a=b,b=c,d=2")
        t = tool.ToolCli(args)
        self.assertEquals(t.args.mode, 'tags')
        self.assertItemsEqual(t._tags, ['a=b', 'b=c', 'd=2'])

    def test_tags(self):
        args = self._mock_args(taglist="dc=a,cluster=b,service=apache2")
        t = tool.ToolCli(args)
        self.assertItemsEqual(t.tags, ['a', 'b', 'apache2'])
        args = self._mock_args(mode='find')
        t = tool.ToolCliFind(args)
        self.assertEquals(t.tags, [])
        args = self._mock_args(
            mode='find',
            object_type='node',
        )
        t = tool.ToolCliFind(args)
        self.assertEquals(t.entity.__name__, 'Node')

    def test_host_list_find(self):
        args = self._mock_args(
            mode="find",
            object_type='node',
        )

        t = tool.ToolCliFind(args)
        t._namedef = 'cp1048.example.com'
        res = [
            node.Node('test', 'cache',
                      'ssl', 'cp1048.example.com'),
            node.Node('test', 'cache',
                      'http', 'cp1048.example.com'),
        ]
        t.entity.find = mock.MagicMock(return_value=res)
        tres = [o for o in t.host_list()]
        self.assertEquals(tres, res)
        t.entity.find.assert_called_with(t._namedef)

    def test_hosts_list_tags(self):
        """Tests getting the host list"""
        host_dir = [
            ('cp1011.example.com', {'pooled': 'yes'}),
            ('cp1020.example.com', {'pooled': 'no'}),
            ('cp1014.local', {'pooled': 'no'})
        ]
        self._mock_list(host_dir)
        args = self._mock_args(taglist="dc=a,cluster=b,service=apache2")

        def tagged(args, name, act):
            t = tool.ToolCli(args)
            t._namedef = name
            t._action = act
            return [el for el in t._tagged_host_list()]

        # Getting a single node
        l = tagged(args, 'a_node_name', 'get')
        self.assertEquals(l, ['a_node_name'])

        # Getting all nodes
        l = tagged(args, 'all', 'dummy')
        self.assertItemsEqual(l, [k for (k, v) in host_dir])

        # GET of all nodes is a special case
        l = tagged(args, 'all', 'get')
        self.assertEquals(l, [])

        # Regex matching
        l = tagged(args, 're:.*\.local', 'get')
        self.assertEquals(l, ['cp1014.local'])

        # All nodes set raise a system exit
        with self.assertRaises(SystemExit):
            tagged(args, 'all', 'set')

        # Majority of nodes via a regex will raise a system exit
        with self.assertRaises(SystemExit):
            tagged(args, 're:cp10(11|20)\.example\.com', 'set')

    def test_parse_args(self):
        # Taglist
        cmdline = ['tags', 'dc=a,cluster=b', '--action', 'get', 'all']
        args = tool.parse_args(cmdline)
        self.assertEquals(args.mode, 'tags')
        self.assertEquals(args.taglist, 'dc=a,cluster=b')
        self.assertEquals(args.action, [['get', 'all']])
