import os
import contextlib
from conftool.cli import syncer
from conftool import service, node
from conftool.tests.integration import IntegrationTestBase
import tempfile
import yaml
import shutil


@contextlib.contextmanager
def temp_data(services, nodes=None):
    directory = tempfile.mkdtemp()
    services_dir = os.path.join(directory, 'service')
    nodes_dir = os.path.join(directory, 'node')
    os.mkdir(services_dir)
    os.mkdir(nodes_dir)
    services_file = os.path.join(services_dir, 'test.yaml')
    nodes_file = os.path.join(nodes_dir, 'test.yaml')
    with open(services_file, 'w') as fh:
        yaml.dump({'test': services}, fh)
    if nodes is not None:
        with open(nodes_file, 'w') as fh:
            yaml.dump({'testdc': nodes}, fh)
    yield directory
    shutil.rmtree(directory)


class SyncerIntegration(IntegrationTestBase):

    @staticmethod
    def service_generator(base_servname, number, initial=0):
        data = {}
        for i in xrange(initial, number):
            servname = base_servname + str(i)
            data[servname] = {'default_values': {"pooled": "yes", "weight": i},
                              'datacenters': ['kitchen_sink', 'sofa']}
        return data

    @staticmethod
    def nodelist_generator(servnames, number, initial=0):
        return {nodename: servnames for nodename
                in ["node-%d" % i for i in xrange(initial, number)]}

    def node_generator(self, cluster, servnames, number, initial=0):
        return {cluster: self.nodelist_generator(servnames, number, initial)}

    def test_load_services(self):
        data = self.service_generator('espresso-machine', 10)
        with temp_data(data) as basepath:
            sync = syncer.Syncer('/nonexistent', basepath)
            sync.load()

        for i in xrange(10):
            servname = 'espresso-machine' + str(i)
            s = service.Service('test', servname)
            self.assertEquals(
                s.default_values, data[servname]['default_values'])

    def test_remove_services(self):
        cluster = 'test'
        data = self.service_generator('espresso-machine', 10)
        with temp_data(data) as basepath:
            sync = syncer.Syncer('/nonexistent', basepath)
            sync.load()
        data = self.service_generator('espresso-machine', 1)
        with temp_data(data) as basepath:
            sync = syncer.Syncer('/nonexistent', basepath)
            sync.load()
        s = service.Service(cluster, 'espresso-machine0')
        self.assertTrue(s.exists)
        for i in xrange(1, 10):
            servname = 'espresso-machine' + str(i)
            s = service.Service(cluster, servname)
            self.assertFalse(s.exists)

    def test_load_nodes(self):
        dc = 'testdc'
        cluster = 'test'
        services = self.service_generator('espresso-machine', 2)
        nodes = self.node_generator(cluster, services.keys(), 20)
        with temp_data(services, nodes) as basepath:
            sync = syncer.Syncer('/nonexistent', basepath)
            sync.load()

        for servname in services.keys():
            for i in xrange(20):
                nodename = "node-%d" % i
                n = node.Node(dc, cluster, servname, nodename)
                self.assertTrue(n.exists)
                self.assertEquals(n.pooled, 'yes')

    def test_remove_nodes(self):
        dc = 'testdc'
        cluster = 'test'
        services = self.service_generator('espresso-machine', 2)
        nodes = self.node_generator(cluster, services.keys(), 20)
        with temp_data(services, nodes) as basepath:
            sync = syncer.Syncer('/nonexistent', basepath)
            sync.load()

        nodes =  self.node_generator(cluster, services.keys(), 10)
        with temp_data(services, nodes) as basepath:
            sync = syncer.Syncer('/nonexistent', basepath)
            sync.load()
        for servname in services.keys():
            for i in xrange(10):
                nodename = "node-%d" % i
                n = node.Node(dc, cluster, servname, nodename)
                self.assertTrue(n.exists)
            for i in xrange(10, 20):
                nodename = "node-%d" % i
                n = node.Node(dc, cluster, servname, nodename)
                self.assertFalse(n.exists)
