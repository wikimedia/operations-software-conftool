import yaml

config = {}
backend = None


class ActionError(Exception):
    pass


class Action(object):

    def __init__(self, obj, act):
        self.entity = obj
        self.action, self.args = self._parse_action(act)
        self.description = ""

    def _parse_action(self, act):
        # TODO: Move this to the cli.tool submodule
        # TODO: make the parsing of the argument a bit more formal
        if act.startswith('get'):
            return ('get', None)
        elif act.startswith('delete'):
            return ('delete', None)
        elif not act.startswith('set/'):
            raise ActionError("Cannot parse action %s" % act)
        set_arg = act.replace('set/', '', 1)
        if set_arg.startswith('@'):
            return ('set', self._from_file(set_arg))
        try:
            values = dict((el.strip().split('=')) for el in set_arg.split(':'))
        except Exception:
            raise ActionError("Could not parse set instructions: %s" % set_arg)
        return ('set', self._from_cli(values))

    def _from_cli(self, values):
        for k, v in values.items():
            try:
                exp_type = self.entity._schema[k].expected_type
            except KeyError:
                # not in the schema, pass it down the lane as-is
                continue

            if exp_type == 'list':
                values[k] = v.split(',')
            elif exp_type == 'bool':
                v = v.lower()
                if v == 'true':
                    values[k] = True
                elif v == 'false':
                    values[k] = False
                else:
                    raise ValueError("Booleans can only be 'true' or 'false'")
            elif exp_type == 'dict':
                raise ValueError("Dictionaries are still not supported on the command line")
        return values

    def _from_file(self, arg):
        filename = arg[1:]
        with open(filename, 'r') as fh:
            try:
                values = yaml.load(fh.read())
            except yaml.parser.ParserError as e:
                raise ActionError("Invalid yaml file: {}".format(e))

        return values

    def run(self):
        if self.action == 'get':
            self.entity.fetch()
            if self.entity.exists:
                return str(self.entity)
            else:
                return "%s not found" % self.entity.name
        elif self.action == 'delete':
            self.entity.delete()
            entity_type = self.entity.__class__.__name__,
            return "Deleted %s %s." % (entity_type,
                                       self.entity.name)
        elif self.action == 'set':
            if not self.entity.exists:
                raise ActionError("Entity %s doesn't exist" % self.entity.name)
            desc = []
            for (k, v) in self.args.items():
                curval = getattr(self.entity, k)
                if v != curval:
                    msg = "%s: %s changed %s => %s" % (
                        self.entity.name, k,
                        curval, v)
                    desc.append(msg)
            self.entity.update(self.args)
            return "\n".join(desc)
