from unittest import mock, TestCase

import etcd

from conftool import configuration
from conftool.drivers import BackendError
from conftool.drivers.etcd import get_config
from conftool import backend


class EtcdDriverTestCase(TestCase):
    def setUp(self):
        c = configuration.Config(driver="etcd")
        b = backend.Backend(c)
        self.driver = b.driver

    def test_init(self):
        self.assertIsInstance(self.driver.client, etcd.Client)

    @mock.patch("etcd.Client.read")
    def test_is_dir(self, etcd_mock):
        etcd_mock.return_value.dir = True
        self.assertTrue(self.driver.is_dir("/none"))
        etcd_mock.assert_called_with("/none")
        etcd_mock.side_effect = etcd.EtcdKeyNotFound
        self.assertFalse(self.driver.is_dir("/test"))

    def test_data(self):
        mockResult = mock.MagicMock()
        mockResult.dir = True
        mockResult.value = None
        self.assertIsNone(self.driver._data(mockResult))
        mockResult.dir = False
        mockResult.value = '{"a": "b"}'
        self.assertEqual(self.driver._data(mockResult), {"a": "b"})
        mockResult.value = "{]}"
        self.assertRaises(BackendError, self.driver._data, mockResult)

    @mock.patch("os.path.exists")
    @mock.patch("os.path.expanduser")
    @mock.patch("conftool.drivers.etcd.yaml_safe_load")
    @mock.patch.dict("os.environ", {"USER": "zebra"})
    def test_get_config(self, mock_yaml_safe_load, mock_expanduser, mock_exists):
        """Tests the behavior of the etcdrc search logic in get_config."""
        # All but /home/zebra/.etcdrc exist.
        mock_exists.side_effect = [True, False, True]
        mock_expanduser.return_value = "/home/zebra"
        mock_yaml_safe_load.side_effect = [
            {"a": 1, "b": 2},  # /etc/etcd/etcdrc
            {"a": 3, "c": 4},  # /path/to/config/etcdrc
        ]
        # Result: get_config returns a merged config, reflecting the order in
        # which existing configs have been loaded.
        self.assertEqual(get_config("/path/to/config/etcdrc"), {"a": 3, "b": 2, "c": 4})
        mock_exists.assert_has_calls(
            [
                mock.call("/etc/etcd/etcdrc"),
                mock.call("/home/zebra/.etcdrc"),
                mock.call("/path/to/config/etcdrc"),
            ]
        )
        mock_expanduser.assert_called_with("~zebra")
        mock_yaml_safe_load.assert_has_calls(
            [
                mock.call("/etc/etcd/etcdrc", default={}),
                mock.call("/path/to/config/etcdrc", default={}),
            ]
        )
