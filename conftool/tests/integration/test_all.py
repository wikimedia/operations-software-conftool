import os

from conftool.cli import syncer, tool
from conftool.tests.integration import IntegrationTestBase

fixtures_base = os.path.realpath(os.path.join(
    os.path.dirname(__file__), os.path.pardir, 'fixtures'))


class MockArg(object):
    schema = None
    object_type = 'horse'

    def __init__(self, selector):
        self.selector = selector


class ConftoolTestCase(IntegrationTestBase):
    def test_all_cycle(self):
        schema_path = os.path.join(fixtures_base, 'schema.yaml')
        MockArg.schema = schema_path
        # Run a first sync
        sync = syncer.Syncer(
            schema_path,
            os.path.join(fixtures_base, 'integration_cycle_data')
        )
        sync.load()
        # Now let's modify a single object
        t = tool.ToolCliByLabel(MockArg('name=Varenne'))
        t._action = 'get'

        for obj in t.host_list():
            obj.update({'height': 167})
        # Let's delete another one
        t = tool.ToolCliByLabel(MockArg('name=Secretariat'))
        t._action = 'get'
        for obj in t.host_list():
            obj.delete()
        # Now let's re-run the syncer and verify it's back
        sync.load()
        t = tool.ToolCliByLabel(MockArg('breed=runner'))
        t._action = 'get'
        hosts = [obj for obj in t.host_list()]
        self.assertEqual(len(hosts), 2)
