import os
import sys
from conftool.cli import syncer, tool
from conftool import service, node
from conftool.tests.integration import IntegrationTestBase, test_base
from contextlib import contextmanager
from StringIO import StringIO
import json

@contextmanager
def captured_output():
        new_out, new_err = StringIO(), StringIO()
        old_out, old_err = sys.stdout, sys.stderr
        try:

            sys.stdout, sys.stderr = new_out, new_err
            yield sys.stdout, sys.stderr
        finally:
            sys.stdout, sys.stderr = old_out, old_err

class SyncerIntegration(IntegrationTestBase):

    def setUp(self):
        args = ['--directory', os.path.join(test_base, 'fixtures')]
        syncer.main(arguments=args)

    def generate_args(self, *actions):
        args = ['--tags', "dc=eqiad,cluster=cache_text,service=https"]
        for action in actions:
            args.append('--action')
            args.extend(action.split())
        return args

    def test_get_node(self):
        args = self.generate_args('get cp1008')
        print args
        with captured_output() as (out, err):
            tool.main(cmdline=args)
        res = out.getvalue().strip()
        output = json.loads(res)
        self.assertEquals(output.keys(), ['cp1008'])
        self.assertEquals(output['cp1008']['pooled'], 'no')
