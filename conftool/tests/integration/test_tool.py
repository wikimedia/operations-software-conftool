import os
import sys
from conftool.cli import syncer, tool
from conftool.tests.integration import IntegrationTestBase, test_base
from conftool import node
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


class ToolIntegration(IntegrationTestBase):

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
        with captured_output() as (out, err):
            tool.main(cmdline=args)
        res = out.getvalue().strip()
        output = json.loads(res)
        self.assertEquals(output.keys(), ['cp1008'])
        self.assertEquals(output['cp1008']['pooled'], 'no')

    def test_change_node_regexp(self):
        """
        Test changing values according to a regexp
        """
        args = self.generate_args('set/pooled=yes re:cp105.')
        tool.main(cmdline=args)
        for hostname in ['cp1052', 'cp1053', 'cp1054', 'cp1055']:
                n = node.Node('eqiad', 'cache_text', 'https', hostname)
                self.assertTrue(n.exists)
                self.assertEquals(n.pooled, "yes")

    def test_create_returns_error(self):
        """
        Test creation is not possible from confctl
        """
        args = self.generate_args('set/pooled=yes re:cp1059')
        tool.main(cmdline=args)
        n = node.Node('eqiad', 'cache_text', 'https', 'cp1059')
        self.assertFalse(n.exists)
