import re

from collections import defaultdict, OrderedDict


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

    def __init__(self, schema, instance, section):
        # TODO: we don't actually use schema, only schema.entities; maybe take that as arg instead?
        self.entity = schema.entities['mwconfig']
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
              db1: 0
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
            config[dc] = {'sectionLoads': {}, 'groupLoadsBySection': {},
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

                self._add_main(
                    config[datacenter]['sectionLoads'], section_key, instance.name, main_weight,
                    is_master=(instance.name == masters[section_name])
                )
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

    def _add_main(self, config, section, instance, weight, is_master=False):
        """Add sectionloads info from an instance into the configuration"""
        # If the section is not present, add it to the config
        # First element of the dict must be the master, so order matters.
        if section not in config:
            config[section] = OrderedDict([(instance, weight)])
        else:
            config[section][instance] = weight
        if is_master:
            # Master to the front!
            config[section].move_to_end(instance, last=False)

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
                master = list(section)[0]
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
                num_slaves = len(section) - 1
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
        # TODO: add a locking mechanism
        # TODO: show a visual diff and ask for confirmation
        sections = [s for s in self.section.get_all(initialized_only=True)]
        config = self.compute_config(
            sections,
            self.instance.get_all(initialized_only=True))

        errors = self.check_config(config, sections)
        if errors:
            return (False, errors)
        for dc, data in config.items():
            for name, value in data.items():
                obj = self.entity(dc, name)
                # verify we conform to the json schema
                try:
                    obj.validate({'val': value})
                except ValueError as e:
                    return (False, [
                        'Object {} failed to validate:'.format(obj.name),
                        str(e),
                        'The actual value was: {}'.format(value)
                    ])
                obj.val = value
                obj.write()
        return (True, None)
