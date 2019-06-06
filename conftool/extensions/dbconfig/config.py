import json
import re

from collections import defaultdict, OrderedDict
from datetime import datetime
from pathlib import Path

from conftool import get_username


class DbConfig:
    """
    Interact with the db-related objects in conftool's mwconfig object class.

    This class allows to fetch the current live config, to sync it with the
    content of the instance/section data, while checking the new data for
    correctness before saving them.
    """
    # in WMF's Mediawiki deploy, 's3' is a special 'DEFAULT' section with
    # wikis that pre-date the section-izing of databases.
    default_section = 's3'
    object_identifier = 'mwconfig'
    cache_file_suffix = '.json'
    cache_file_datetime_format = '%Y%m%d-%H%M%S'

    def __init__(self, schema, instance, section):
        # TODO: we don't actually use schema, only schema.entities; maybe take that as arg instead?
        self.entity = schema.entities[DbConfig.object_identifier]
        self.section = section
        self.instance = instance

    # TODO: is this truly a @property?  They aren't really immutable nor
    # part of the state of this instance.
    @property
    def live_config(self):
        """
        The configuration stored under mwconfig, that is used
        by MediaWiki.

        The data structure we expect is something like:
        dc:
          sectionLoads:
            s1:
              [
                {db1: 0},  # master
                {db2: 50, db3: 150, ...}  # slaves
              ]
            ...
          groupLoadsBySection:
            s1:
              vslow:
                db2: 1
            ...

        """
        selector = {'name': re.compile('^(readOnlyBySection|sectionLoads|groupLoadsBySection)$')}
        config = defaultdict(dict)
        for obj in self.entity.query(selector):
            dc = obj.tags['scope']
            config[dc][obj.name] = obj.val
        return config

    # TODO: is this truly a @property?  They aren't really immutable nor
    # part of the state of this instance.
    @property
    def config_from_dbstore(self):
        return self.compute_config(
            self.section.get_all(initialized_only=True),
            self.instance.get_all(initialized_only=True))

    def compute_config(self, sections, instances):
        """
        Given a set of sections and instances, calculate the configuration
        that would be used by MediaWiki.

        The output data structure is the same returned from `DbConfig.live_config`
        """
        # The master for each section
        section_masters = defaultdict(dict)
        for obj in sections:
            section_masters[obj.tags['datacenter']][obj.name] = obj.master
        config = {}
        # Let's initialize the variables
        for dc in section_masters.keys():
            config[dc] = {'sectionLoads': defaultdict(lambda: [{}, {}]), 'groupLoadsBySection': {},
                          'readOnlyBySection': {}}

        # Fill in the readonlybysection data
        for obj in sections:
            if not obj.readonly:
                continue
            config[obj.tags['datacenter']]['readOnlyBySection'][obj.name] = obj.reason

        # now fill them with the content of instances
        for instance in instances:
            datacenter = instance.tags['datacenter']
            masters = section_masters[datacenter]
            for section_name, section in instance.sections.items():
                # If the corresponding section is not defined, skip it
                if section_name not in masters:
                    # TODO: is this worth logging?
                    continue

                # Do not add the instance if not pooled
                if not section['pooled']:
                    continue

                fraction = section['percentage']/100
                # Mangle the key.
                # Thanks for this, MediaWiki
                if section_name == self.default_section:
                    section_key = 'DEFAULT'
                else:
                    section_key = section_name

                main_weight = int(section['weight'] * fraction)
                section_load_index = 1
                if instance.name == masters[section_name]:
                    section_load_index = 0
                section_load = config[datacenter]['sectionLoads'][section_key]
                section_load[section_load_index][instance.name] = main_weight

                if 'groups' not in section:
                    continue
                for group_name, group in section['groups'].items():
                    weight = int(group['weight'] * fraction)
                    self._add_group(
                        config[datacenter]['groupLoadsBySection'], section_key,
                        instance.name, group_name, weight
                    )
        return config

    def _add_group(self, config, section, instance, group, weight):
        """Add groupbysection info from an instance into the configuration"""
        if section not in config:
            config[section] = defaultdict(OrderedDict)
        config[section][group][instance] = weight

    def check_config(self, config, sections):
        """
        Checks the validity of a configuration
        """
        errors = []
        for dc, mwconfig in config.items():
            # in each section, check:
            # 1 - a master is defined
            # 2 - at least N instances are pooled.
            for name, section in mwconfig['sectionLoads'].items():
                if name == 'DEFAULT':
                    name = self.default_section

                section_errors = self._check_section(name, section)
                if section_errors:
                    errors += section_errors
                    continue

                master = next(iter(section[0]))
                my_sections = [s for s in sections if name == s.name
                               and s.tags['datacenter'] == dc]
                if not my_sections:
                    errors.append('Section {} is not configured'.format(name))
                    continue

                my_section = my_sections[0]
                if master != my_section.master:
                    errors.append(
                        'Section {section} is supposed to have master'
                        ' {master} but had {found} instead'.format(
                            section=name, master=my_section.master, found=master
                        )
                    )
                min_pooled = my_section.min_slaves
                num_slaves = len(section[1])
                if num_slaves < min_pooled:
                    errors.append(
                        'Section {section} is supposed to have '
                        'minimum {N} slaves, found {M}'.format(
                            section=name, N=min_pooled, M=num_slaves)
                    )
        return errors

    def check_instance(self, instance):
        """
        Given an appropriate mwconfig object, swaps out the one in the current config
        for the new one, and checks preventively if the resulting configuration would
        be ok.
        """
        dc = instance.tags['datacenter']
        sections = [s for s in self.section.get_all(initialized_only=True)]
        # Swap the instance we want to check in the live config
        instances = [inst for inst in self.instance.get_all(initialized_only=True)
                     if not (inst.name == instance.name and inst.tags['datacenter'] == dc)]
        instances.append(instance)
        new_config = self.compute_config(sections, instances)
        return self.check_config(new_config, sections)

    def check_section(self, section):
        """
        Given an appropriate mwconfig object, swaps out the one in the current config
        for the new one, and checks preventively if the resulting configuration would
        be ok.
        """
        # Swap the instance we want to check in the live config
        dc = section.tags['datacenter']
        sections = [s for s in self.section.get_all(initialized_only=True)
                    if not (s.name == section.name and s.tags['datacenter'] == dc)]
        sections.append(section)
        instances = [inst for inst in self.instance.get_all(initialized_only=True)]
        new_config = self.compute_config(sections, instances)
        return self.check_config(new_config, sections)

    def commit(self):
        """
        Translates the current configuration from the db objects
        to the one read by MediaWiki, validates it and writes the objects to
        the datastore.
        """
        try:
            previous_config = self.live_config
        except Exception as e:
            previous_config = None
            rollback_message = ('Unable to backup previous configuration. Failed to fetch it: '
                                '{e}').format(e=e)

        # TODO: add a locking mechanism
        # TODO: show a visual diff and ask for confirmation
        sections = [s for s in self.section.get_all(initialized_only=True)]
        config = self.compute_config(
            sections,
            self.instance.get_all(initialized_only=True))

        errors = self.check_config(config, sections)
        if errors:
            return (False, errors)

        # Save current config for easy rollback
        if previous_config is not None:
            cache_file_name = '{date}-{user}{suffix}'.format(
                date=datetime.now().strftime(DbConfig.cache_file_datetime_format),
                user=get_username(),
                suffix=DbConfig.cache_file_suffix)
            cache_file_path = Path(self.entity.config.cache_path).joinpath(
                DbConfig.object_identifier)
            try:  # TODO Python3.4 doesn't accept exist_ok=True
                Path(cache_file_path).mkdir(mode=0o755, parents=True)
            except FileExistsError:
                pass

            # TODO: when Python3.4 and 3.5 support is removed, remove the str()
            cache_file = cache_file_path.joinpath(cache_file_name)
            try:
                with open(str(cache_file), 'w') as f:
                    json.dump(previous_config, f, indent=4, sort_keys=True)
            except Exception as e:
                rollback_message = ('Unable to backup previous configuration. Failed to save it: '
                                    '{e}').format(e=e)
            else:
                rollback_message = ('Previous configuration saved. To restore it run: '
                                    'dbctl config restore {path}').format(path=cache_file)

        return self._write(config, rollback_message=rollback_message)

    def restore(self, file_object):
        """Restore the configuration from the given file object."""
        # TODO: add a locking mechanism
        # TODO: show a visual diff and ask for confirmation
        errors = []
        try:
            config = json.load(file_object)
        except ValueError as e:  # TODO: Python 3.4 doesn't have json.JSONDecodeError
            errors.append('Invalid JSON configuration: {e}'.format(e=e))
            return (False, errors)

        for dc, mwconfig in config.items():
            for name, section in mwconfig['sectionLoads'].items():
                errors += self._check_section(name, section)

        if errors:
            return (False, errors)

        return self._write(config)

    def _write(self, config, *, rollback_message=None):
        """Write the given config, if valid, to the datastore."""
        for dc, data in config.items():
            for name, value in data.items():
                obj = self.entity(dc, name)
                try:  # verify we conform to the json schema
                    obj.validate({'val': value})
                except ValueError as e:
                    # TODO: should any other object already written be rolled-back?
                    errors = ['Object {} failed to validate:'.format(obj.name),
                              str(e),
                              'The actual value was: {}'.format(value)]
                    if rollback_message is not None:
                        errors.insert(0, rollback_message)
                    return (False, errors)

                obj.val = value
                obj.write()

        messages = None
        if rollback_message is not None:
            messages = [rollback_message]

        return (True, messages)

    def _check_section(self, name, section):
        """Checks the validity of a section in sectionLoads."""
        errors = []
        if not section[0]:
            errors.append('Section {} has no master'.format(name))
        elif len(section[0]) != 1:
            errors.append('Section {name} has multiple masters: {masters}'.format(
                name=name, masters=sorted(section[0].keys())))

        return errors
