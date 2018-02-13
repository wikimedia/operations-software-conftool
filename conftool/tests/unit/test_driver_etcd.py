import unittest

import etcd
import mock

from conftool import configuration
from conftool.drivers import BackendError
from conftool import backend

class EtcdDriverTestCase(unittest.TestCase):

    def setUp(self):
        c = configuration.Config(driver="etcd")
        b = backend.Backend(c)
        self.driver = b.driver

    def test_init(self):
        self.assertIsInstance(self.driver.client, etcd.Client)

    @mock.patch('etcd.Client.read')
    def test_is_dir(self, etcd_mock):
        etcd_mock.return_value.dir = True
        self.assertTrue(self.driver.is_dir('/none'))
        etcd_mock.assert_called_with('/none')
        etcd_mock.side_effect = etcd.EtcdKeyNotFound
        self.assertFalse(self.driver.is_dir('/test'))

    def test_data(self):
        mockResult = mock.MagicMock()
        mockResult.dir = True
        mockResult.value = None
        self.assertIsNone(self.driver._data(mockResult))
        mockResult.dir = False
        mockResult.value = '{"a": "b"}'
        self.assertEqual(self.driver._data(mockResult), {"a": "b"})
        mockResult.value = '{]}'
        self.assertRaises(BackendError, self.driver._data, mockResult)
