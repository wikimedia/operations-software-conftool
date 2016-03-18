import unittest
import mock
from conftool.kvobject import KVObject
from conftool import service, drivers
from conftool import configuration
from conftool.tests.unit import MockBackend


class TestService(unittest.TestCase):

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

    @mock.patch('conftool.service.Service.get_default')
    def test_new_service(self, mocker):
        """New service creation"""
        mocker.return_value = 'default_value'
        self._mock_read(None)
        n = service.Service('cluster', 'foo')
        # Test
        self.assertEquals(n.base_path(), 'services')
        self.assertEquals(n.key, 'services/cluster/foo')
        self.assertFalse(n.exists)
        self.assertEquals(n.datacenters, 'default_value')
        self.assertEquals(n.name, 'foo')

    def test_read(self):
        """Test that reading fetches correctly the values"""
        self._mock_read({"datacenters": ['a', 'b', 'c'],
                         "default_values": {"pooled": "no"},
                         "something_else": "some_value"})
        s = service.Service('cluster', 'foo')
        self.assertEquals(s.datacenters, ['a', 'b', 'c'])
        self.assertEquals(s.default_values['pooled'], "no")
        self.assertEquals(s._schemaless['something_else'], 'some_value')

    def test_failed_validation(self):
        """Test bad validation"""
        self._mock_read({"datacenters": "maybe?", "default_values": 20})
        s = service.Service('cluster', 'foo')
        self.assertEquals(s.datacenters, [])
        self.assertEquals(s.default_values, {'pooled': "no", "weight": 0})

    def test_tags(self):
        self._mock_read({"datacenters": ['a', 'b', 'c'],
                         "default_values": {"pooled": "no"},
                         "something_else": "some_value"})
        s = service.Service('cluster', 'foo')
        self.assertEquals(s.tags, {'cluster': 'cluster'})

    def test_dir(self):
        self.assertEquals(service.Service.dir('a'), 'services/a')
