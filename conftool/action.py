import os
import shlex
import subprocess
import tempfile

import yaml

from conftool import yaml_safe_load, kvobject


config = {}
backend = None


class ActionError(Exception):
    pass


class ActionValidationError(ActionError):
    pass


def get_action(obj, act):
    action, _, value = act.partition("/")

    if action == "get":
        return GetAction(obj)
    elif action == "delete":
        return DelAction(obj)
    elif action == "set":
        return SetAction(obj, value)
    elif action == "edit":
        return EditAction(obj)
    else:
        raise ActionError("Could not parse action %s" % act)


class GetAction:
    """Action to perform when a get request is involved"""

    def __init__(self, obj):
        self.entity = obj

    def run(self):
        self.entity.fetch()
        if self.entity.exists:
            return str(self.entity)
        else:
            return "%s not found" % self.entity.name


class DelAction(GetAction):
    """Action to perform when deleting an object"""

    def run(self):
        self.entity.delete()
        entity_type = (self.entity.__class__.__name__,)
        return "Deleted %s %s." % (entity_type, self.entity.name)


class EditAction(GetAction):
    """Edit the object in an editor"""

    DEFAULT_EDITOR = "/usr/bin/editor"  # You all know emacs should be the default...

    def __init__(self, obj):
        self.entity = obj
        # This is a container for edited values
        self.edited = {}
        self.temp = None

    def run(self):
        try:
            self._to_file()
            while True:
                self._edit()
                # TODO: seems Golangish; a more Pythonic way is to have _validate_edit throw a
                # custom exception, and here catch it & run _check_amend.
                valid, err = self._validate_edit()
                if valid:
                    break
                else:
                    self._check_amend(err)
            self.entity.update(self.edited)
            return "Entity {} successfully updated".format(self.entity.pprint())
        finally:
            os.unlink(self.temp)

    def _validate_edit(self):
        try:
            self.entity.validate(self.edited)
            return (True, None)
        except Exception as e:  # pragma: no coverage
            # TODO: why no coverage here?
            if isinstance(self.entity, kvobject.JsonSchemaEntity):
                print("The modified object fails JSON validation, please check it!")
                print("Reported reason: {}".format(e))
            else:
                print("The modified object is not valid, please check it!")
                print("Reported reason: {}".format(e))
            return (False, e)

    def _check_amend(self, exception):  # pragma: no coverage
        while True:
            answer = input("Continue editing? [y/n] ")
            lc_answer = answer.lower()
            if lc_answer == "y":
                break
            elif lc_answer == "n":
                raise exception
            else:
                print("Please answer y/n!")
                continue

    def _to_file(self):
        if self.temp is None:  # pragma: no coverage
            f = tempfile.NamedTemporaryFile(delete=False)
            self.temp = f.name
        else:
            f = open(self.temp, "wb")
        f.write("# Editing object {}\n".format(self.entity.pprint()).encode("utf-8"))
        self.entity.fetch()
        yaml.safe_dump(self.entity._to_net(), stream=f, encoding="utf-8")
        f.close()

    def _edit(self):
        editor = os.environ.get("EDITOR", self.DEFAULT_EDITOR)
        editor_cmd = shlex.split(editor)
        editor_cmd.append(self.temp)
        rv = subprocess.call(editor_cmd)
        if rv != 0:
            raise ActionError("Editor {} returned nonzero {}".format(editor, rv))
        self.edited = yaml_safe_load(self.temp)


class SetAction:
    def __init__(self, obj, act):
        """Action to perform when editing an object"""
        self.entity = obj
        if not self.entity.exists:
            raise ActionError("Entity %s doesn't exist" % self.entity.name)

        self.args = self._parse_action(act)
        self.description = ""

    def _parse_action(self, arg):
        # TODO: make the parsing of the argument a bit more formal
        if arg.startswith("@"):
            return self._from_file(arg)
        try:
            values = dict((el.strip().split("=")) for el in arg.split(":"))
        except Exception:
            raise ActionError("Could not parse set instructions: %s" % arg)
        return self._from_cli(values)

    def _from_cli(self, values):
        for k, v in values.items():
            try:
                exp_type = self.entity._schema[k].expected_type
            except KeyError:
                # not in the schema, pass it down the lane as-is
                continue

            if exp_type == "list":
                values[k] = v.split(",")
            elif exp_type == "bool":
                v = v.lower()
                if v == "true":
                    values[k] = True
                elif v == "false":
                    values[k] = False
                else:
                    raise ValueError("Booleans can only be 'true' or 'false'")
            elif exp_type == "dict":
                raise ValueError("Dictionaries are still not supported on the command line")
        return values

    def _from_file(self, arg):
        filename = arg[1:]

        try:
            values = yaml_safe_load(filename)
        except Exception as e:
            raise ActionError(str(e))
        return values

    def run(self):
        # Validate the new data *before* updating the object
        try:
            self.entity.validate(self.args)
        except Exception as e:
            raise ActionValidationError("The provided data is not valid: %s" % e)

        desc = []
        for k, v in self.args.items():
            curval = getattr(self.entity, k)
            if v != curval:
                msg = "%s: %s changed %s => %s" % (self.entity.pprint(), k, curval, v)
                desc.append(msg)
        self.entity.update(self.args)
        return "\n".join(desc)
