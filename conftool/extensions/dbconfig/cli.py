import json
import sys

from conftool.cli.tool import ToolCliBase
from conftool.extensions.dbconfig.action import ActionResult
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
        result = getattr(self, '_run_on_{}'.format(self.args.object_name))()
        if not result.success:
            print('Execution FAILED\nReported errors:', file=sys.stderr)
        if result.messages:
            print('\n'.join(result.messages), file=sys.stderr)

        if result.announce_message:
            self.irc.warning(result.announce_message)

        return result.exit_code

    def _get_result(self, success, errors):
        """Get a default ActionResult instance based on success (bool) and errors (list of str)."""
        return ActionResult(success, 0 if success else 1, messages=errors)

    def _run_on_instance(self):
        name = self.args.instance_name
        cmd = self.args.command
        datacenter = self.args.scope
        if cmd == 'get':
            if name == ALL_SELECTOR:
                all_instances = [s.asdict() for s in self.instance.get_all(dc=datacenter)]
                for instance in sorted(all_instances, key=lambda d: (d['tags'], sorted(d.keys()))):
                    print(json.dumps(instance))
                return ActionResult(True, 0)

            try:
                res = self.instance.get(name, datacenter)
            except Exception as e:
                return ActionResult(False, 1, messages=['Unexpected error:', str(e)])
            if res is None:
                return ActionResult(False, 2, messages=["DB instance '{}' not found".format(name)])
            else:
                print(json.dumps(res.asdict(), indent=4, sort_keys=True))
                return ActionResult(True, 0)
        elif cmd == 'edit':
            return self._get_result(*self.instance.edit(name, datacenter=datacenter))
        elif cmd == 'depool':
            return self._get_result(*self.instance.depool(name, self.args.section, self.args.group))
        elif cmd == 'pool':
            return self._get_result(*self.instance.pool(
                name, self.args.percentage, self.args.section, self.args.group))
        elif cmd == 'set-weight':
            return self._get_result(*self.instance.weight(
                name, self.args.weight, self.args.section, self.args.group))

    def _run_on_section(self):
        name = self.args.section_name
        cmd = self.args.command
        datacenter = self.args.scope
        if cmd == 'get':
            if name == ALL_SELECTOR:
                all_sections = [s.asdict() for s in self.section.get_all(dc=datacenter)]
                for section in sorted(all_sections, key=lambda d: (d['tags'], sorted(d.keys()))):
                    print(json.dumps(section))
                return ActionResult(True, 0)

            try:
                res = self.section.get(name, datacenter)
            except ValueError as e:
                return ActionResult(False, 1, messages=[str(e)])

            if res is None:
                return ActionResult(False, 2, messages=["DB section '{}' not found".format(name)])
            else:
                print(json.dumps(res.asdict(), indent=4, sort_keys=True))
                return ActionResult(True, 0)
        elif cmd == 'set-master':
            instance_name = self.args.instance_name
            candidate_master = self.instance.get(instance_name, dc=self.args.scope)
            if candidate_master is None:
                return ActionResult(
                    False, 2, messages=["DB instance '{}' not found".format(instance_name)])

            if name not in candidate_master.sections:
                return ActionResult(
                    False,
                    3,
                    messages=["DB instance '{}' is not configured for section '{}'".format(
                        instance_name, name)])

            return self._get_result(*self.section.set_master(name, datacenter, instance_name))
        elif cmd == 'edit':
            return self._get_result(*self.section.edit(name, datacenter))
        elif cmd == 'ro':
            return self._get_result(*self.section.set_readonly(
                name, datacenter, True, self.args.reason))
        elif cmd == 'rw':
            return self._get_result(*self.section.set_readonly(name, datacenter, False))

    def _run_on_config(self):
        cmd = self.args.command
        dc = self.args.scope
        if cmd == 'commit':
            return self.db_config.commit(batch=self.args.batch, datacenter=dc)
        elif cmd == 'restore':
            return self.db_config.restore(self.args.file, datacenter=dc)
        elif cmd == 'diff':
            config, errors = self.db_config.compute_and_check_config()
            if errors:
                return ActionResult(False, 3,
                                    messages=['Could not generate configuration:'] + errors)

            if dc is not None:
                if dc not in (self.db_config.live_config.keys() | config.keys()):
                    return ActionResult(False, 2, messages=['Datacenter {} not found'.format(dc)])

            has_diff, diff = self.db_config.diff_configs(
                self.db_config.live_config, config, datacenter=dc)

            if has_diff and not self.args.quiet:
                sys.stdout.writelines(diff)

            return ActionResult(True, int(has_diff))
        elif cmd == 'generate':
            config, errors = self.db_config.compute_and_check_config()
            if dc is not None:
                if dc not in config:
                    messages = ['Datacenter {} not found in generated configuration'.format(dc)]
                    messages += errors
                    return ActionResult(False, 2, messages=messages)

                config = config[dc]

            print(json.dumps(config, indent=4, sort_keys=True))
            return self._get_result(errors is None or not errors, errors)
        elif cmd == 'get':
            config = self.db_config.live_config
            if dc is not None:
                if dc not in config:
                    messages = ['Datacenter {} not found in live configuration'.format(dc)]
                    return ActionResult(False, 2, messages=messages)

                config = config[dc]

            print(json.dumps(config, indent=4, sort_keys=True))
            return ActionResult(True, 0)
