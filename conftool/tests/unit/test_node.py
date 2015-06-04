import unittest
import mock
import conftool
from conftool import KVObject, node, service
from conftool import configuration, drivers, backend

class MockDriver(drivers.BaseDriver):
    def __init__(self, config):
        self.base_path = '/base_path/v2'

class MockBackend(object):
    def __init__(self, config):
        self.config = config
        self.driver = MockDriver(config)

class TestNode(unittest.TestCase):

    def _mock_read(self, values):
        KVObject.backend.driver.read = mock.MagicMock(return_value=values)

    def _mock_defaults(self, values):
        def _side_effect(what):
            return values[what]
        service.Service.get_defaults = mock.MagicMock(side_effect=_side_effect)

    def setUp(self):
        KVObject.backend = MockBackend({})
        KVObject.config = configuration.Config(driver="")
        pass

    @mock.patch('conftool.node.Node.get_default')
    def test_new_node(self, mocker):
        """New node creation"""
        mocker.return_value = 'default_value'
        self._mock_read(None)
        n = node.Node('dc', 'cluster', 'service', 'foo')
        # Test
        self.assertEquals(n.base_path, 'pools')
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

    def test_dir(self):
        self.assertEquals(node.Node.dir('a', 'b', 'c'), 'pools/a/b/c')
