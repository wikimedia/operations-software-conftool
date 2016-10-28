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

    def test_host_multiple_services(self):
        """Set all services in a single host w/ and w/o the --host flag"""
        # The query return a single host with multiple services
        query_result = [
            node.Node('dc', 'cluster', 'service_a', 'host_a'),
            node.Node('dc', 'cluster', 'service_b', 'host_a'),
            node.Node('dc', 'cluster', 'service_c', 'host_a')]

        args = self._mock_args(selector='name=cp3009.esams.wmnet', host=False)
        cli = tool.ToolCliByLabel(args)
        cli._action = 'set'
        cli.entity.query = mock.MagicMock(return_value=query_result)

        # With args.host=False we expect raw_input question, answering yes
        with mock.patch('__builtin__.raw_input', return_value='y') as _raw:
            cli.host_list()
            _raw.assert_called_once_with('confctl>')

        # With args.host=False we expect raw_input question, answering no
        with mock.patch('__builtin__.raw_input', return_value='n') as _raw:
            self.assertRaises(SystemExit, cli.host_list)

        # With args.host=True we do not expect raw_input questions
        cli.args.host = True
        with mock.patch('__builtin__.raw_input') as _raw:
            cli.host_list()
            self.assertEquals(_raw.call_args_list, [])

        # Adding another host to the query result
        query_result.append(node.Node('dc', 'cluster', 'service_a', 'host_b'))
        cli.entity.query = mock.MagicMock(return_value=query_result)

        # With args.host=True we expect raw_input question, answering y
        with mock.patch('__builtin__.raw_input', return_value='y') as _raw:
            cli.host_list()
            _raw.assert_called_once_with('confctl>')

    def test_parse_args(self):
        # Taglist
        cmdline = ['tags', 'dc=a,cluster=b', '--action', 'get', 'all']
        args = tool.parse_args(cmdline)
        self.assertEquals(args.mode, 'tags')
        self.assertEquals(args.taglist, 'dc=a,cluster=b')
        self.assertEquals(args.action, [['get', 'all']])
