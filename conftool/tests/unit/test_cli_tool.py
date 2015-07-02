import unittest
import mock
from conftool import KVObject, configuration
from conftool.tests.unit import MockBackend
from conftool.cli import tool


class TestCliTool(unittest.TestCase):

    def setUp(self):
        KVObject.backend = MockBackend({})
        KVObject.config = configuration.Config(driver="")

    def _mock_list(self, values):
        KVObject.backend.driver.ls = mock.MagicMock(return_value=values)

    def test_get_hosts(self):
        """Tests getting the host list"""
        host_dir = [
            ('cp1011.example.com', {'pooled': 'yes'}),
            ('cp1020.example.com', {'pooled': 'no'}),
            ('cp1014.local', {'pooled': 'no'})
        ]
        self._mock_list(host_dir)
        l = tool.host_list('simple', '/whatever', 'get')
        self.assertEquals(l, ['simple'])
        l = tool.host_list('all', '/whatever', 'dummy')
        self.assertItemsEqual(l, [k for (k, v) in host_dir])
        l = tool.host_list('all', '/whatever', 'get')
        self.assertEquals(l, [])
        l = tool.host_list('re:.*\.local', '/whatever', 'get')
        self.assertEquals(l, ['cp1014.local'])
        l = tool.host_list('re:cp10[1-2][0-3]', '/whatever', 'get')
        self.assertItemsEqual(l, ['cp1011.example.com', 'cp1020.example.com'])
        with self.assertRaises(SystemExit):
            tool.host_list('all', '/something', 'set')
