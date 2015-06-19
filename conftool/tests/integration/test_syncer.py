import os
from conftool.cli import syncer
from conftool import service, node
from conftool.tests.integration import IntegrationTestBase, test_base


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

    def test_tag_files(self):
        d = os.path.join(test_base, 'fixtures')
        res = syncer.tag_files(d)
        self.assertEquals(
            res['services'][0], os.path.join(d, 'services/data.yaml'))

    def test_load_service(self):
        cluster = 'test'
        servname = 'espresso-machine'
        data = {'default_values': {"pooled": "yes", "weight": 0},
                'datacenters': ['kitchen_sink', 'sofa']}
        syncer.load_service(cluster, servname, data)
        s = service.Service(cluster, servname)
        self.assertEquals(s.default_values["pooled"], "yes")
        self.assertEquals(s.datacenters[0], 'kitchen_sink')

    def test_load_services(self):
        cluster = 'test'
        data = self.service_generator('espresso-machine', 10)
        syncer.load_services(cluster, data.keys(), data)
        for i in xrange(10):
            servname = 'espresso-machine' + str(i)
            s = service.Service(cluster, servname)
            self.assertEquals(
                s.default_values, data[servname]['default_values'])

    def test_remove_services(self):
        cluster = 'test'
        data = self.service_generator('espresso-machine', 10)
        syncer.load_services(cluster, data.keys(), data)
        del data['espresso-machine0']
        syncer.remove_services(cluster, data.keys())
        s = service.Service(cluster, 'espresso-machine0')
        self.assertTrue(s.exists)
        for i in xrange(1, 10):
            servname = 'espresso-machine' + str(i)
            s = service.Service(cluster, servname)
            self.assertFalse(s.exists)

    def test_get_service_actions(self):
        cluster = 'test'
        data = self.service_generator('espresso-machine', 10)
        syncer.load_services(cluster, data.keys(), data)
        new_data = self.service_generator('espresso-machine', 15, initial=5)
        new_data['espresso-machine6']['datacenters'] = ['sofa']
        (new, delete) = syncer.get_service_actions(cluster, new_data)
        # Pick one machine that is new
        self.assertIn('espresso-machine12', new)
        # one removed
        self.assertIn('espresso-machine4', delete)
        # one modified
        self.assertIn('espresso-machine6', new)
        # one not modified at all
        self.assertNotIn('espresso-machine7', new)
        self.assertNotIn('espresso-machine7', delete)

    def test_load_node(self):
        cluster = 'test'
        sdata = self.service_generator('espresso-machine', 2, initial=1)
        syncer.load_services(cluster, sdata.keys(), sdata)
        serv = sdata.keys().pop()
        syncer.load_node('sofa', cluster, serv, 'one-off')
        n = node.Node('sofa', cluster, serv, 'one-off')
        self.assertTrue(n.exists)
        self.assertEquals(n.weight, sdata[serv]['default_values']['weight'])

    def test_get_changed_nodes(self):
        dc = 'sofa'
        cluster = 'test'
        sdata = self.service_generator('espresso-machine', 2, 1)
        syncer.load_services(cluster, sdata.keys(), sdata)
        for i in xrange(10):
            syncer.load_node(dc, cluster, 'espresso-machine1', 'node-%d' % i)
        expected_hosts = ["node-%d" % i for i in xrange(5, 15)]
        n, d = syncer.get_changed_nodes(dc, cluster,
                                        'espresso-machine1',  expected_hosts)
        self.assertIn('node-13', n)
        self.assertIn('node-4', d)

    def test_load_nodes(self):
        dc = 'sofa'
        cluster = 'test'
        sdata = self.service_generator('espresso-machine', 2)
        syncer.load_services(cluster, sdata.keys(), sdata)
        data = self.node_generator(cluster, sdata.keys(), 20)
        syncer.load_nodes(dc, data)
        for servname in sdata.keys():
            for i in xrange(20):
                nodename = "node-%d" % i
                n = node.Node(dc, cluster, servname, nodename)
                self.assertTrue(n.exists)
                self.assertEquals(n.pooled, 'yes')
