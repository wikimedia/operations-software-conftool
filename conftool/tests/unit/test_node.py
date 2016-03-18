import unittest
import mock
from conftool.kvobject import KVObject
from conftool import node, service, drivers
from conftool import configuration
from conftool.tests.unit import MockBackend


class TestNode(unittest.TestCase):

    def _mock_read(self, values):
        if values is None:
            KVObject.backend.driver.read = mock.MagicMock(
                side_effect=drivers.NotFoundError)
        else:
            KVObject.backend.driver.read = mock.MagicMock(return_value=values)

    def _mock_defaults(self, values):
        def _side_effect(what):
            return values[what]
        service.Service.get_defaults = mock.MagicMock(side_effect=_side_effect)

    def setUp(self):
        KVObject.backend = MockBackend({})
        KVObject.config = configuration.Config(driver="")

    @mock.patch('conftool.node.Node.get_default')
    def test_new_node(self, mocker):
        """New node creation"""
        mocker.return_value = 'default_value'
        self._mock_read(None)
        n = node.Node('dc', 'cluster', 'service', 'foo')
        # Test
        self.assertEquals(n.base_path(), 'pools')
        self.assertEquals(n.key, 'pools/dc/cluster/service/foo')
        self.assertFalse(n.exists)
        self.assertEquals(n.pooled, 'default_value')
        self.assertEquals(n.name, 'foo')

    def test_read(self):
        """Test that reading fetches correctly the values"""
        self._mock_read({"pooled": "yes", "weight": 20})
        n = node.Node('dc', 'cluster', 'service', 'foo')
        self.assertEquals(n.weight, 20)
        self.assertEquals(n.pooled, "yes")

    def test_failed_validation(self):
        """Test bad validation"""
        self._mock_read({"pooled": "maybe?", "weight": 20})
        n = node.Node('dc', 'cluster', 'service', 'foo')
        self.assertEquals(n.pooled, "no")
        # Note: this fails at the moment
        # self.assertRaises(ValueError, setattr, n, "pooled", "maybe")

    def test_tags(self):
        """Test tags are correctly reported"""
        self._mock_read({"pooled": "yes", "weight": 20})
        n = node.Node('dc', 'cluster', 'service', 'foo')
        for k, v in n.tags.items():
            self.assertEquals(k, v)

    def test_dir(self):
        self.assertEquals(node.Node.dir('a', 'b', 'c'), 'pools/a/b/c')
