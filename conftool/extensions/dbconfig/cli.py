import json

from conftool.cli.tool import ToolCliBase
from conftool.extensions.dbconfig.config import DbConfig
from conftool.extensions.dbconfig.entities import Instance, Section


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
        if success:
            print("Execution successful")
        else:
            print("Execution FAILED")
            print("Reported errors:\n{}".format("\n".join(err)))
        return success

    def _run_on_instance(self):
        name = self.args.instance_name
        cmd = self.args.command
        datacenter = self.args.scope
        if cmd == 'get':
            try:
                res = self.instance.get(name, datacenter)
            except Exception as e:
                return(False, ['Unexpected error:', str(e)])
            if res is None:
                return (False, ["DB instance '{}' not found".format(name)])
            else:
                print(str(res))
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
        return (False, ['Unknown command {}'.format(cmd)])

    def _run_on_section(self):
        name = self.args.section_name
        cmd = self.args.command
        datacenter = self.args.scope
        if cmd == 'get':
            try:
                res = self.section.get(name, datacenter)
            except ValueError as e:
                return (False, [str(e)])

            if res is None:
                return (False, ["DB section '{}' not found".format(name)])
            else:
                print(str(res))
                return (True, None)
        elif cmd == 'edit':
            return self.section.edit(name, datacenter)
        elif cmd == 'set-master':
            return self.section.set_master(name, datacenter, self.args.instance_name)
        elif cmd == 'ro':
            return self.section.set_readonly(name, datacenter, True, self.args.reason)
        elif cmd == 'rw':
            return self.section.set_readonly(name, datacenter, False)

    def _run_on_config(self):
        cmd = self.args.command
        if cmd == 'commit':
            return self.db_config.commit()
        elif cmd == 'get':
            print(json.dumps(self.db_config.live_config))
            return (True, None)
