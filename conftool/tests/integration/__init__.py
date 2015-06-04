import os
import time
import logging
import subprocess
import unittest
import shutil
import tempfile
from conftool import configuration, KVObject

test_base = os.path.realpath(os.path.join(
    os.path.dirname(__file__), '..'))


class EtcdProcessHelper(object):

    def __init__(
            self,
            base_directory,
            proc_name='etcd',
            port=2379,
            internal_port=2380,
            cluster=False,
            tls=False
    ):

        self.base_directory = base_directory
        self.proc_name = proc_name
        self.port = port
        self.internal_port = internal_port
        self.proc = None
        self.cluster = cluster
        self.schema = 'http://'
        if tls:
            self.schema = 'https://'

    def run(self, proc_args=None):
        log = logging.getLogger()
        if self.proc is not None:
            raise Exception("etcd already running with pid %d", self.proc.pid)
        client = '%s127.0.0.1:%d' % (self.schema, self.port)
        daemon_args = [
            self.proc_name,
            '-data-dir', self.base_directory,
            '-name', 'test-node',
            '-advertise-client-urls', client,
            '-listen-client-urls', client
        ]
        if proc_args:
            daemon_args.extend(proc_args)

        daemon = subprocess.Popen(daemon_args)
        log.debug('Started %d' % daemon.pid)
        log.debug('Params: %s' % daemon_args)
        time.sleep(2)
        self.proc = daemon

    def stop(self):
        self.proc.kill()
        self.proc = None


class IntegrationTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        program = cls._get_exe()
        cls.directory = tempfile.mkdtemp(prefix='conftool')
        cls.processHelper = EtcdProcessHelper(
            cls.directory,
            proc_name=program, port=2379)
        cls.processHelper.run()
        cls.fixture_dir = os.path.join(test_base, 'fixtures')
        conf = configuration.get(None)
        KVObject.setup(conf)

    @classmethod
    def tearDownClass(cls):
        cls.processHelper.stop()
        shutil.rmtree(cls.directory)

    @classmethod
    def _is_exe(cls, fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    @classmethod
    def _get_exe(cls):
        PROGRAM = 'etcd'
        program_path = None
        for path in os.environ["PATH"].split(os.pathsep):
            path = path.strip('"')
            exe_file = os.path.join(path, PROGRAM)
            if cls._is_exe(exe_file):
                program_path = exe_file
                break
        if not program_path:
            raise Exception('etcd not in path!!')
        return program_path

    def tearDown(self):
        path = KVObject.backend.driver.base_path
        try:
            KVObject.backend.driver.client.delete(path, recursive=True, dir=True)
        except:
            pass
