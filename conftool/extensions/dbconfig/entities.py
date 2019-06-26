import copy
import re
import textwrap

from abc import ABC, abstractmethod

from conftool.action import EditAction
from conftool.drivers import BackendError


ALL_GROUPS = 'all'  # Special group name to select all configured groups


class DbEditAction(EditAction):
    """Specific derived action for editing db objects"""

    def __init__(self, obj, checker, example):
        super().__init__(obj)
        self.checker = checker
        self.example = example

    def _to_file(self):
        super()._to_file()
        if self.example is None:
            return

        with open(self.temp, 'a') as f:
            f.write('\n# Full object example (all commented lines are automatically discarded)')
            f.write(textwrap.indent(textwrap.dedent(self.example), '#'))

    def _validate_edit(self):
        try:
            # We run a base check delegating to the actual conftool entity
            self.entity.validate(self.edited)
            # We update a copy of the object, and feed it to the
            # appropriate checker that we set up
            to_check = copy.deepcopy(self.entity)
            to_check.from_net(self.edited)
            errors = self.checker(to_check)
            return (len(errors) == 0, errors)
        except Exception as e:
            print("The modified object fails validation: {}".format(e))
            return (False, e)


class DbObjBase(ABC):
    """Abstract base class for interacting with the db-like objects"""
    selectors = {'datacenter': re.compile(r'^\w+$'), 'name': re.compile(r'.*')}
    label = None
    example = None

    def __init__(self, schema, checker=None):
        """
        Spawns a DB object.
        Parameters:

        * schema: a conftool schema object
        * checker: an (optional) checker for the generated global configuration
        """
        self.entity = schema.entities['dbconfig-{}'.format(self.label)]
        self.checker = checker

    def get_all(self, name='.*', initialized_only=False, dc=None):
        """
        Gets a range of dbconfig objects, all by default
        """
        for obj in self.entity.query(self._query(name, dc)):
            if initialized_only and self._check_uninitialized(obj):
                continue
            else:
                yield obj

    def get(self, name, dc=None):
        '''
        Gets one dbconfig object.

        Parameters:
        * name (string): The name of the object to search for

        Returns: the entity if present, None otherwise.

        Raises: ValueError if multiple objects by the same name exist.
        '''
        results = list(self.get_all(name, dc=dc))
        count = len(results)
        if count > 1:
            raise ValueError(
                "{count} {label}s found for query '{query}' and scope '{dc}', expected 1.".format(
                    count=count, label=self.label, query=name, dc=dc))
        elif count == 1:
            return results[0]
        else:
            return None

    def _query(self, name, dc=None):
        """Format the conftool query to perform."""
        query = self.selectors.copy()
        # TODO: it would be nice to re.escape() name and dc before using them here,
        # but get_all() needs rethinking before that can happen.
        query['name'] = re.compile('^{}$'.format(name))
        if dc is not None:
            query['datacenter'] = re.compile('^{}$'.format(dc))
        return query

    def edit(self, name, datacenter=None):
        obj = self.get(name, datacenter)
        if obj is None:
            if datacenter is None:
                return (
                    False,
                    ['No {} found with name "{}"; please provide a datacenter'.format(
                        self.label, name)]
                )
            obj = self.entity(datacenter, name)
        act = DbEditAction(obj, self.checker, self.example)
        try:
            act.run()
            return (True, None)
        except Exception as e:
            return (False, [str(e)])

    def _check_state(self, obj):
        try:
            if obj is None:
                return ['{} not found'.format(self.label)]

            # If the current object doesn't conform to the json schema
            # refuse to operate on it
            obj.validate({})
        except ValueError as e:
            return [str(e)]

        if self._check_uninitialized(obj):
            # The object is uninitialized. We can't act on it
            return ['{} is uninitialized'.format(self.label)]

    # TODO: _update and _check_uninitialized need docstrings!
    @abstractmethod
    def _update(self,  obj, callback, **args):
        pass

    @abstractmethod
    def _check_uninitialized(self, obj):
        pass

    # TODO: this isn't a decorator in Pythonic terms.
    def write_callback(self, callback, id, **args):
        """
        Decorator that wraps modifications to the conftool objects.

        Apply this decorator to a callback modifying the object, it
        will take care of calling _set_state, passing the callback along.
        """
        obj = self.get(*id)
        errors = self._check_state(obj)
        if errors is not None:
            return (False, errors)

        try:
            # Now the object-type-dependent part
            # Swap the name with the actual object
            errors = self._update(obj, callback, **args)
            if errors:
                return (False, errors)
            obj.write()
            return (True, None)
        except BackendError as e:
            return (False, [str(e)])


class Instance(DbObjBase):
    """Manages configurations for MediaWiki database configuration objects"""
    label = 'instance'
    example = """
    host_ip: 10.0.0.1
    port: 3306
    sections:
      s1:
        groups:
          dump:
            pooled: true
            weight: 100
          vslow:
            pooled: true
            weight: 100
        percentage: 100
        pooled: true
        weight: 200
      s2:
        percentage: 100
        pooled: true
        weight: 200
    """

    def depool(self, instance, section=None, group=None):
        """
        Depools a database from all sections, or just a specific section/group

        Parameters:
        * instance: the instance name
        * section: the database section to operate on (optional)
        * group: the database group to operate on (optional)

        Returns: a tuple (result, error)
        """
        if group is not None and section is None:
            return (False, ['Cannot select a group but not a section'])

        def set_depooled(obj, section, group):
            if group is None:
                obj.sections[section]['pooled'] = False
            elif group == ALL_GROUPS:
                for group_data in obj.sections[section]['groups'].values():
                    group_data['pooled'] = False
            else:
                obj.sections[section]['groups'][group]['pooled'] = False

        return self.write_callback(set_depooled, (instance, ), section=section, group=group)

    def pool(self, instance, percentage=None, section=None, group=None):
        """
        Pools a database from all sections, or just a specific section/group

        Parameters:
        * instance: the instance name
        * percentage: the pooling percentage, useful during warmups
        * section: the database section to operate on (optional)
        * group: the database group to operate on (optional)

        Returns: a tuple (result, error)
        """
        if group is not None and section is None:
            return (False, ['Cannot select a group but not a section'])
        if percentage is not None and group is not None:
            return (False, ['Percentages are only supported for global pooling'])
        # TODO: checking default values doesn't let us differentiate between
        # nothing provided vs the default values explicitly provided.

        def set_pooled(obj, section, group):
            if group is None:
                obj.sections[section]['pooled'] = True
                if percentage is not None:
                    obj.sections[section]['percentage'] = percentage
            elif group == ALL_GROUPS:
                for group_data in obj.sections[section]['groups'].values():
                    group_data['pooled'] = True
            else:
                obj.sections[section]['groups'][group]['pooled'] = True

        return self.write_callback(set_pooled, (instance, ), section=section, group=group)

    def weight(self, instance, new_weight, section=None, group=None):
        """
        Modifies weight of the database in all sections, or a specific section/group

        Parameters:
        * instance: the instance name
        * new_weight: the new weight of the database
        * section: the database section to operate on (optional)
        * group: the database group to operate on (optional)

        Returns: a tuple (result, error)
        """
        if group is not None and section is None:
            return (False, ['Cannot select a group but not a section'])

        def set_weight(obj, section, group):
            if group is None:
                obj.sections[section]['weight'] = new_weight
            elif group == ALL_GROUPS:
                for group_data in obj.sections[section]['groups'].values():
                    group_data['weight'] = new_weight
            else:
                obj.sections[section]['groups'][group]['weight'] = new_weight
        return self.write_callback(set_weight, (instance, ), section=section, group=group)

    # "Private" methods
    def _update(self, obj, callback, section=None, group=None, **kwargs):
        # If the section we're supposed to operate upon is
        # not found, raise an error. New sections should be
        # added via the edit interface
        if section is not None and section not in obj.sections.keys():
            return ['Section "{}" is not configured for {}'.format(section, obj.name)]
        errors = []
        for my_section in obj.sections.keys():
            # Skip section if a selection is made
            # and we're not in the correct one
            if section is not None and section != my_section:
                continue

            # Modify the dataset using the provided callback.
            # Given obj is a JsonSchemaEntity, it will be modified as well
            try:
                callback(obj, my_section, group)
            except KeyError as e:
                # Manage the error scenario where we're trying to act on the
                # wrong key.
                missing = e.args[0].rstrip()
                if missing == 'groups':
                    # TODO: this detection can easily fail; KeyError on a nested dict will of
                    # course not give the 'full path'. We're assuming here that there will never
                    # be a nested key called 'groups', or a group named like a top-level key.
                    errors.append("No groups are configured for section '{}'".format(section))
                elif missing == group:
                    errors.append(
                        'Group "{}" is not configured in section "{}"'.format(group, section)
                    )
                else:
                    errors.extend(
                        ['Callback failed for section {} group {}'.format(my_section, group),
                            str(e)]
                    )
            except Exception as e:
                # In this specific case, we exit the loop, as an unmanaged error has happened.
                errors.extend(['Callback failed!', str(e)])
                return errors
        if errors:
            return errors
        # Now verify that the overall configuration makes sense.
        # Please note this would need to happen in a transaction.
        return self.checker(obj)

    def _check_uninitialized(self, obj):
        return (obj.sections == {})


class Section(DbObjBase):
    "Manages the configuration of a database section"
    label = 'section'

    def set_master(self, section, datacenter, new_master):
        def cb_set_master(obj):
            obj.master = new_master
        return self.write_callback(cb_set_master, (section, datacenter))

    def set_readonly(self, section, datacenter, readonly, reason=None):
        def cb_set_readonly(obj):
            obj.readonly = readonly
            if reason is not None:
                obj.ro_reason = reason
        return self.write_callback(cb_set_readonly, (section, datacenter))

    def _update(self, obj, callback, **args):
        # Modify the object
        try:
            callback(obj)
        except Exception as e:
            return ['Callback failed!', str(e)]
        # check the object
        return self.checker(obj)

    def _check_uninitialized(self, obj):
        return (obj.master == 'PLACEHOLDER')
