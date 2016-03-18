from contextlib import contextmanager
import json
import mock
import os
import sys
from StringIO import StringIO

from conftool.cli import syncer, tool
from conftool.tests.integration import IntegrationTestBase, test_base
from conftool import node
from conftool import _log


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

    def output_for(self, args):
        with captured_output() as (out, err):
            tool.main(cmdline=args)
        res = out.getvalue().strip()
        output = []
        if not res:
            return []

        try:
            for line in res.split("\n"):
                output.append(json.loads(line))
        except:
            raise ValueError(res)
        return output

    def generate_args(self, *actions):
        args = ['tags', "dc=eqiad,cluster=cache_text,service=https"]
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
        k = output.keys()
        k.sort()
        self.assertEquals(k, ['cp1008', 'tags'])
        self.assertEquals(output['cp1008']['pooled'], 'no')

    def test_find_node(self):
        args = ['find', '--action', 'get', 'cp1008']
        output = self.output_for(args)
        self.assertEquals(len(output), 3)
        for serv in output:
            self.assertIn(serv['tags']['service'],
                          ['varnish-be', 'https', 'varnish-fe'])
        # Test that old-style parameters are still valid
        args = ['--find', '--action', 'get', 'cp1008']
        output = self.output_for(args)
        self.assertEquals(len(output), 3)

    def test_change_node_regexp(self):
        """
        Changing values according to a regexp
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

    def test_select_nodes(self):
        args = ['select', 'cluster=appservers,name=mw101.*', 'get']
        output = self.output_for(args)
        self.assertEquals(len(output), 2)
        # Now let's select appservers and https termination
        args = ['select', 'dc=eqiad,service=(https|apache)', 'get']
        output = self.output_for(args)
        self.assertEquals(len(output), 41)

    def test_select_raise_warning(self):

        # Check that the warning gets called upon if we select more than
        # one node, or not if we don't
        args = ['select', 'cluster=appservers', 'set/pooled=yes']
        tool.ToolCliByLabel.raise_warning = mock.MagicMock()
        tool.main(cmdline=args)
        self.assertEquals(tool.ToolCliByLabel.raise_warning.call_count,1)
        # now let's loop through the responses from conftool get
        args = ['select', 'cluster=appservers', 'get']
        for res in self.output_for(args):
            _log.debug(res)
            del res['tags']
            k = res.keys()[0]
            self.assertEquals(res[k]['pooled'], 'yes')
        tool.ToolCliByLabel.raise_warning.reset_mock()
        args = ['select', 'name=mw1018', 'set/pooled=inactive']
        tool.main(cmdline=args)
        tool.ToolCliByLabel.raise_warning.assert_not_called()
        out = self.output_for(['select', 'name=mw1018', 'get'])
        self.assertEquals(out[0]['mw1018']['pooled'], 'inactive')


    def test_select_empty(self):
        # Test that regexes are anchored and a partial name will not
        # get us any result.
        out = self.output_for(['select', 'name=w1018', 'get'])
        self.assertEquals(out, [])
        out = self.output_for(['select', 'name=mw101', 'get'])
        self.assertEquals(out, [])
