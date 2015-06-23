config = {}
backend = None


class ActionError(Exception):
    pass


class Action(object):

    def __init__(self, obj, act):
        self.action, self.args = self._parse_action(act)
        self.entity = obj
        self.description = ""

    def _parse_action(self, act):
        if act.startswith('get'):
            return ('get', None)
        elif act.startswith('delete'):
            return ('delete', None)
        elif not act.startswith('set/'):
            raise ActionError("Cannot parse action %s" % act)
        set_arg = act.replace('set/', '', 1)
        try:
            values = dict((el.strip().split('=')) for el in set_arg.split(':'))
        except Exception:
            raise ActionError("Could not parse set instructions: %s" % set_arg)
        return ('set', values)

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
        else:
            desc = []
            for (k, v) in self.args.items():
                msg = "%s: %s changed %s => %s" % (
                    self.entity.name, k,
                    getattr(self.entity, k), v)
                desc.append(msg)
            self.entity.update(self.args)
            return "\n".join(desc)
