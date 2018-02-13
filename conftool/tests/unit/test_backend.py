import unittest

import mock

from conftool import backend, configuration

class TestBackend(unittest.TestCase):

    def test_init(self):
        c = configuration.Config()
        bcknd = backend.Backend(c)
        self.assertEqual(bcknd.driver.base_path, "/conftool/v1")
        with mock.patch('conftool.backend.open', mock.mock_open) as mocker:
            mocker.side_effect = Exception('test')
            self.assertRaises(SystemExit, backend.Backend, c)
