import json
import sys

from conftool.cli.tool import ToolCliBase
from conftool.extensions.dbconfig.config import DbConfig
from conftool.extensions.dbconfig.entities import Instance, Section


ALL_SELECTOR = 'all'


class DbConfigCli(ToolCliBase):
    """
    CLI for dbconfig.
    """

    def __init__(self, args):
        super().__init__(args)
        self.db_config = DbConfig(self._schema, Instance(self._schema), Section(self._schema))
        self.instance = Instance(self._schema, self.db_config.check_instance)
        self.section = Section(self._schema, self.db_config.check_section)

    def run_action(self):
        """
        This is the entrypoint for cli execution. We overload the original cli
        behaviour by selecting which sub-cli to use based on args.object_name
        """
        # TODO: the below uses a Golang-ish idiom
        if self.args.object_name == 'instance':
            success, err = self._run_on_instance()
        elif self.args.object_name == 'section':
            success, err = self._run_on_section()
        elif self.args.object_name == 'config':
            success, err = self._run_on_config()
        # TODO: could perhaps be cleaner by building a dict of name->method, or
        # by dynamically getting methods based on object_name
        if not success:
            print('Execution FAILED\nReported errors:', file=sys.stderr)
        if err:  # Print messages also on success, if any
            print('\n'.join(err), file=sys.stderr)
        return success

    def _run_on_instance(self):
        name = self.args.instance_name
        cmd = self.args.command
        datacenter = self.args.scope
        if cmd == 'get':
            if name == ALL_SELECTOR:
                all_instances = [s.asdict() for s in self.instance.get_all(dc=datacenter)]
                for instance in sorted(all_instances, key=lambda d: (d['tags'], sorted(d.keys()))):
                    print(json.dumps(instance))
                return (True, None)

            try:
                res = self.instance.get(name, datacenter)
            except Exception as e:
                return(False, ['Unexpected error:', str(e)])
            if res is None:
                return (False, ["DB instance '{}' not found".format(name)])
            else:
                print(json.dumps(res.asdict(), indent=4, sort_keys=True))
                return (True, None)
        elif cmd == 'edit':
            return self.instance.edit(name, datacenter=datacenter)
        elif cmd == 'depool':
            return self.instance.depool(name, self.args.section, self.args.group)
        elif cmd == 'pool':
            return self.instance.pool(name, self.args.percentage,
                                      self.args.section, self.args.group)
        elif cmd == 'set-weight':
            return self.instance.weight(name, self.args.weight, self.args.section, self.args.group)

    def _run_on_section(self):
        name = self.args.section_name
        cmd = self.args.command
        datacenter = self.args.scope
        if cmd == 'get':
            if name == ALL_SELECTOR:
                all_sections = [s.asdict() for s in self.section.get_all(dc=datacenter)]
                for section in sorted(all_sections, key=lambda d: (d['tags'], sorted(d.keys()))):
                    print(json.dumps(section))
                return (True, None)

            try:
                res = self.section.get(name, datacenter)
            except ValueError as e:
                return (False, [str(e)])

            if res is None:
                return (False, ["DB section '{}' not found".format(name)])
            else:
                print(json.dumps(res.asdict(), indent=4, sort_keys=True))
                return (True, None)
        elif cmd == 'edit':
            return self.section.edit(name, datacenter)
        elif cmd == 'set-master':
            instance_name = self.args.instance_name
            candidate_master = self.instance.get(instance_name, dc=self.args.scope)
            if candidate_master is None:
                return (False, ["DB instance '{}' not found".format(instance_name)])

            if name not in candidate_master.sections:
                return (False, ["DB instance '{}' is not configured for section '{}'".format(
                    instance_name, name)])

            return self.section.set_master(name, datacenter, instance_name)
        elif cmd == 'ro':
            return self.section.set_readonly(name, datacenter, True, self.args.reason)
        elif cmd == 'rw':
            return self.section.set_readonly(name, datacenter, False)

    def _run_on_config(self):
        cmd = self.args.command
        dc = self.args.scope
        if cmd == 'commit':
            return self.db_config.commit(batch=self.args.batch, datacenter=dc)
        elif cmd == 'diff':
            config, errors = self.db_config.compute_and_check_config()
            if errors:
                return (False, ['Could not generate configuration:'] + errors)

            if dc is not None:
                if dc not in (self.db_config.live_config.keys() | config.keys()):
                    return (False, ['Datacenter {} not found'.format(dc)])

            if not self.args.quiet:
                sys.stdout.writelines(self.db_config.diff_configs(
                    self.db_config.live_config, config, datacenter=dc))

            # TODO: we'd like to plumb through a nonzero exit status but the current interface
            # doesn't make it very easy to indicate "operation successful, but exit nonzero"
            return (True, None)
        elif cmd == 'generate':
            (config, errors) = self.db_config.compute_and_check_config()
            if dc is not None:
                if dc not in config:
                    return (False,
                            ['Datacenter {} not found in generated configuration'.format(dc)]
                            + errors)
                config = config[dc]

            print(json.dumps(config, indent=4, sort_keys=True))
            success = errors is None or len(errors) == 0
            return(success, errors)
        elif cmd == 'get':
            config = self.db_config.live_config
            if dc is not None:
                if dc not in config:
                    return (False, ['Datacenter {} not found in live configuration'.format(dc)])
                config = config[dc]

            print(json.dumps(config, indent=4, sort_keys=True))
            return (True, None)
        elif cmd == 'restore':
            return self.db_config.restore(self.args.file, datacenter=dc)
