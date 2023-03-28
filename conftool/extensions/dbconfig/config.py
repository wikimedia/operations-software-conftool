import difflib
import json
import os
import re
import sys

from collections import defaultdict, OrderedDict
from datetime import datetime
from pathlib import Path

from conftool import get_username
from conftool.extensions.dbconfig.action import ActionResult, phaste

# If we have icdiff installed, use it for interactive output.
# If we don't, fall back to difflib.unified_diff().
try:
    import icdiff
except ImportError:
    icdiff = None


class DbConfig:
    """
    Interact with the db-related objects in conftool's mwconfig object class.

    This class allows to fetch the current live config, to sync it with the
    content of the instance/section data, while checking the new data for
    correctness before saving them.
    """

    # in WMF's Mediawiki deploy, 's3' is a special 'DEFAULT' section with
    # wikis that pre-date the section-izing of databases.
    default_section = "s3"
    object_identifier = "mwconfig"
    object_name = "dbconfig"
    cache_file_suffix = ".json"
    cache_file_datetime_format = "%Y%m%d-%H%M%S"
    # section.schema prevents a KeyError from happening here.
    flavor_to_dbconfig_key = {
        "regular": "sectionLoads",
        "external": "externalLoads",
    }

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
                {db2: 50, db3: 150, ...}  # replicas
              ]
            ...
          groupLoadsBySection:
            s1:
              vslow:
                db2: 1
            ...

        """
        config = {}
        for obj in self.entity.query({"name": re.compile(r"^{}$".format(DbConfig.object_name))}):
            dc = obj.tags["scope"]
            config[dc] = obj.val

        return config

    # TODO: is this truly a @property?  They aren't really immutable nor
    # part of the state of this instance.
    @property
    def config_from_dbstore(self):
        return self.compute_config(
            self.section.get_all(initialized_only=True),
            self.instance.get_all(initialized_only=True),
        )

    def compute_config(self, sections, instances):
        """
        Given a set of sections and instances, calculate the configuration
        that would be used by MediaWiki.

        The output data structure is the same returned from `DbConfig.live_config`
        """
        # The master for and the flavor of each section
        section_masters = defaultdict(dict)
        section_flavors = defaultdict(dict)
        section_omit_replicas = defaultdict(dict)
        for obj in sections:
            section_masters[obj.tags["datacenter"]][obj.name] = obj.master
            section_flavors[obj.tags["datacenter"]][obj.name] = obj.flavor
            section_omit_replicas[obj.tags["datacenter"]][obj.name] = obj.omit_replicas_in_mwconfig
        config = {}
        # Let's initialize the variables
        for dc in section_masters.keys():
            config[dc] = {
                "externalLoads": defaultdict(lambda: [{}, {}]),
                "sectionLoads": defaultdict(lambda: [{}, {}]),
                "groupLoadsBySection": {},
                "readOnlyBySection": {},
                "hostsByName": {},
            }

        # Fill in the readonlybysection data
        for obj in sections:
            if obj.flavor != "regular":
                continue
            if not obj.readonly:
                continue
            section = self._mw_section(obj.name)
            config[obj.tags["datacenter"]]["readOnlyBySection"][section] = obj.ro_reason

        # now fill them with the content of instances
        for instance in instances:
            datacenter = instance.tags["datacenter"]
            masters = section_masters[datacenter]
            if instance.name not in config[datacenter]["hostsByName"]:
                if instance.port == instance.get_default("port"):
                    hostport = instance.host_ip
                else:
                    # TODO: this will not work at all for IPv6 host_ips!
                    hostport = "{}:{}".format(instance.host_ip, instance.port)
                config[datacenter]["hostsByName"][instance.name] = hostport
            for section_name, section in instance.sections.items():
                # If the corresponding section is not defined, skip it
                if section_name not in masters:
                    # TODO: is this worth logging?
                    continue

                # Do not add the instance if not pooled
                if not section["pooled"]:
                    continue

                fraction = section["percentage"] / 100
                section_key = self._mw_section(section_name)

                main_weight = int(section["weight"] * fraction)
                section_load_index = 1
                if instance.name == masters[section_name]:
                    section_load_index = 0
                elif section_omit_replicas[datacenter][section_name]:
                    continue
                section_flavor = section_flavors[datacenter][section_name]
                output_key = self.flavor_to_dbconfig_key[section_flavor]
                section_load = config[datacenter][output_key][section_key]
                section_load[section_load_index][instance.name] = main_weight

                # Groups only work in regular-flavored sections.
                if section_flavor != "regular" or "groups" not in section:
                    continue
                for group_name, group in section["groups"].items():
                    # Instances can be pooled for a section, but depooled from a given group.
                    if not group["pooled"]:
                        continue
                    weight = int(group["weight"] * fraction)
                    self._add_group(
                        config[datacenter]["groupLoadsBySection"],
                        section_key,
                        instance.name,
                        group_name,
                        weight,
                    )
        return config

    def _add_group(self, group_loads_by_section, section, instance, group, weight):
        """Add groupbysection info from an instance into the configuration"""
        if section not in group_loads_by_section:
            group_loads_by_section[section] = defaultdict(OrderedDict)
        group_loads_by_section[section][group][instance] = weight

    def check_config(self, config, sections):
        """
        Checks the validity of a configuration
        """
        errors = []
        for dc, mwconfig in config.items():
            # in each section, check:
            # 1 - a master is defined
            # 2 - at least N instances are pooled.
            for name, section in mwconfig["sectionLoads"].items():
                if name == "DEFAULT":
                    name = self.default_section

                section_errors = self._check_section(name, section)
                if section_errors:
                    errors += section_errors
                    continue

                master = next(iter(section[0]))
                my_sections = [s for s in sections if name == s.name and s.tags["datacenter"] == dc]
                if not my_sections:
                    errors.append("Section {} is not configured".format(name))
                    continue

                my_section = my_sections[0]
                if master != my_section.master:
                    errors.append(
                        "Section {section} is supposed to have master"
                        " {master} but had {found} instead".format(
                            section=name, master=my_section.master, found=master
                        )
                    )
                min_pooled = my_section.min_replicas
                num_replicas = len(section[1])
                if num_replicas < min_pooled:
                    errors.append(
                        "Section {section} is supposed to have "
                        "minimum {N} replicas, found {M}".format(
                            section=name, N=min_pooled, M=num_replicas
                        )
                    )
        return errors

    def check_instance(self, instance):
        """
        Given an appropriate mwconfig object, swaps out the one in the current config
        for the new one, and checks preventively if the resulting configuration would
        be ok.
        """
        dc = instance.tags["datacenter"]
        sections = [s for s in self.section.get_all(initialized_only=True)]
        # Swap the instance we want to check in the live config
        instances = [
            inst
            for inst in self.instance.get_all(initialized_only=True)
            if not (inst.name == instance.name and inst.tags["datacenter"] == dc)
        ]
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
        dc = section.tags["datacenter"]
        sections = [
            s
            for s in self.section.get_all(initialized_only=True)
            if not (s.name == section.name and s.tags["datacenter"] == dc)
        ]
        sections.append(section)
        instances = [inst for inst in self.instance.get_all(initialized_only=True)]
        new_config = self.compute_config(sections, instances)
        return self.check_config(new_config, sections)

    def _validate(self, config, datacenter=None):
        errors = []
        for dc, data in config.items():
            if datacenter is not None and dc != datacenter:
                continue

            obj = self.entity(dc, DbConfig.object_name)
            try:
                obj.validate({"val": data})
            except ValueError as e:
                errors.extend(
                    [
                        "Object {} failed to validate:".format(obj.name),
                        str(e),
                        "The actual value was: {}".format(data),
                    ]
                )

        return errors

    def compute_and_check_config(self, datacenter=None):
        """
        Returns a tuple of (configuration dict, list of errors).
        Runs the checks in check_config as well as validating against the JSON schema.
        """
        # Something subtle here: even when datacenter!=None, we generate configuration
        # using all sections and instances.  It might be relevant in the future if we allow
        # instances to belong to sections from another DC, or some other oddball scenarios.
        sections = [s for s in self.section.get_all(initialized_only=True)]
        config = self.compute_config(sections, self.instance.get_all(initialized_only=True))

        errors = []
        errors.extend(self.check_config(config, sections))
        errors.extend(self._validate(config))
        return (config, errors)

    def diff_configs(
        self, a, b, *, a_name="live", b_name="generated", datacenter=None, force_unified=False
    ):
        """
        Returns a 2-element tuple. The first element is a boolean, True if there is any diff,
        False otherwise. The second element is a generator that yields unified diff lines of
        the deltas between configs a and b.
        The generator returned is akin to the ones returned by difflib.unified_diff, but with
        newlines already included, suitable for passing directly to sys.stdout.writelines().

        The input configs should be formatted like those returned by live_config.

        datacenter should be None (show diffs for all DCs) or exactly a datacenter name.
        """
        # TODO: add support for limiting --scope

        def _get(tree, branches):
            """
            Multi-level dict.get().  branches is an iterable of keys to traverse in tree.
            Will translate any NoneType encountered along the way into {}.  (This is
            important for handling the bootstrapping case where no configuration object yet
            exists in etcd.)
            """
            subtree = tree
            for b in branches:
                if subtree is None or b not in subtree:
                    return {}
                subtree = subtree[b]
            if subtree is None:
                return {}
            return subtree

        def _to_json_lines(tree):
            return json.dumps(tree, indent=4, sort_keys=True).splitlines()

        def _diff_leaf(a, b, branches):
            """Given an 'a' tree and a 'b' tree, compute a diff of _get(a, branches) against
            _get(b, branches)."""
            path = "/".join(branches)
            a_lines = _to_json_lines(_get(a, branches))
            b_lines = _to_json_lines(_get(b, branches))
            a_descr = " ".join([path, a_name])
            b_descr = " ".join([path, b_name])
            if icdiff is not None and not force_unified:
                consolediff = icdiff.ConsoleDiff(cols=self._terminal_columns())
                difflines = list(
                    [
                        line + "\n"
                        for line in consolediff.make_table(
                            a_lines,
                            b_lines,
                            context=True,
                            fromdesc=a_descr,
                            todesc=b_descr,
                        )
                    ]
                )
                # Unlike difflib.unified_diff, icdiff outputs a header regardless of whether or
                # not there was a diff between contents.  Suppress header-only output sections.
                if len(difflines) > 1:
                    rv.extend(difflines)
            else:
                rv.extend(
                    [
                        line + "\n"
                        for line in difflib.unified_diff(
                            a_lines, b_lines, lineterm="", fromfile=a_descr, tofile=b_descr
                        )
                    ]
                )

        def _recursively_diff(a, b, branches):
            """Diff the sub-trees of 'a' and 'b', recursing an extra time for keys_with_subtrees."""
            # These keys have sub-trees with non-trivial structure, so we recurse into them to
            # separately present their leaves to difflib.
            keys_with_subtrees = ("externalLoads", "groupLoadsBySection", "sectionLoads")

            for next_branch in sorted(_get(a, branches).keys() | _get(b, branches).keys()):
                if next_branch in keys_with_subtrees:
                    _recursively_diff(a, b, branches + [next_branch])
                else:
                    _diff_leaf(a, b, branches + [next_branch])

        # _diff_leaf accumulates output into here, a list of diff lines.
        rv = []

        # While it is unlikely that a and b have non-overlapping datacenters,
        # and because of the schema it should be impossible for a[dc] and b[dc] to have
        # non-overlapping sub-keys (e.g. sectionLoads), we should handle both possibilities anyway.
        # We also take care to order sections deterministically in the output.
        for dc in sorted(a.keys() | b.keys()):
            if datacenter is not None:
                if dc != datacenter:
                    continue
            _recursively_diff(a, b, [dc])

        return (bool(rv), rv)

    def commit(self, *, batch=False, datacenter=None, comment=None):
        """
        Translates the current configuration from the db objects
        to the one read by MediaWiki, validates it and writes the objects to
        the datastore.

        if batch=True, we don't show diff and prompt for confirmation.
        """
        try:
            previous_config = self.live_config
        except Exception as e:
            previous_config = None
            rollback_message = (
                "Unable to backup previous configuration. Failed to fetch it: " "{e}"
            ).format(e=e)

        # TODO: add a locking mechanism
        config, errors = self.compute_and_check_config()
        if errors:
            return ActionResult(False, 1, messages=errors)

        if datacenter is not None:
            if datacenter not in config.keys():
                return ActionResult(
                    False, 2, messages=["Datacenter {} not found".format(datacenter)]
                )

        has_diff, diff = self.diff_configs(previous_config, config, datacenter=datacenter)
        if not has_diff:
            return ActionResult(True, 0, messages=["Nothing to commit"])

        # We want to Phab-paste a unified diff, not the two-column icdiff.
        _, unified_diff = self.diff_configs(
            previous_config, config, datacenter=datacenter, force_unified=True
        )

        diff_text = "".join(diff)
        if batch and comment is None:
            return ActionResult(False, 4, messages=["--message required for batch commits"])
        if not batch:
            # TODO: add test coverage
            confirmed, error = self._ask_confirmation(diff_text)
            if not confirmed:
                return ActionResult(False, 3, messages=[error])
            if not sys.stdout.isatty():
                return ActionResult(
                    False, 4, messages=["--batch required when running uninteractively"]
                )
            if comment is None:
                comment = input("Please describe this commit: ")

        # Save current config for easy rollback
        cache_file = None
        if previous_config is not None:
            cache_file_name = "{date}-{user}{suffix}".format(
                date=datetime.now().strftime(DbConfig.cache_file_datetime_format),
                user=get_username(),
                suffix=DbConfig.cache_file_suffix,
            )
            cache_file_path = Path(self.entity.config.cache_path).joinpath(DbConfig.object_name)
            try:  # TODO Python3.4 doesn't accept exist_ok=True
                Path(cache_file_path).mkdir(mode=0o755, parents=True)
            except FileExistsError:
                pass

            # TODO: when Python3.4 and 3.5 support is removed, remove the str()
            cache_file = cache_file_path.joinpath(cache_file_name)
            try:
                with open(str(cache_file), "w") as f:
                    json.dump(previous_config, f, indent=4, sort_keys=True)
            except Exception as e:
                rollback_message = (
                    "Unable to backup previous configuration. Failed to save it: " "{e}"
                ).format(e=e)
            else:
                rollback_message = (
                    "Previous configuration saved. To restore it run: "
                    "dbctl config restore {path}"
                ).format(path=cache_file)

        result = self._write(config, datacenter=datacenter)
        # Inject the rollback message
        result.messages.insert(0, rollback_message)
        datacenter_label = datacenter if datacenter is not None else "all"
        # Publish diff to Phaste
        message_prefix = "{}dbctl commit".format("" if result.success else "FAILED ")
        phaste_title = "{prefix} (dc={dc}): '{msg}'".format(
            prefix=message_prefix, dc=datacenter_label, msg=comment
        )
        phaste_url = phaste(phaste_title, "".join(unified_diff))
        # Set the announce message
        result.announce_message = (
            "{prefix} (dc={dc}): '{msg}', diff saved to " "{url} and previous config saved to {f}"
        ).format(
            prefix=message_prefix, dc=datacenter_label, url=phaste_url, f=cache_file, msg=comment
        )
        return result

    def restore(self, file_object, datacenter=None):
        """Restore the configuration from the given file object."""
        # TODO: add a locking mechanism
        errors = []
        try:
            config = json.load(file_object)
        except ValueError as e:  # TODO: Python 3.4 doesn't have json.JSONDecodeError
            errors.append("Invalid JSON configuration: {e}".format(e=e))
            return ActionResult(False, 1, messages=errors)

        if datacenter is not None:
            if datacenter not in config:
                errors.append(
                    "Datacenter {dc} not found in configuration to be restored".format(
                        dc=datacenter
                    )
                )
                return ActionResult(False, 2, messages=errors)

        for dc, mwconfig in config.items():
            if datacenter is not None and dc != datacenter:
                continue

            for name, section in mwconfig["sectionLoads"].items():
                errors += self._check_section(name, section)

        if errors:
            return ActionResult(False, 3, messages=errors)

        result = self._write(config, datacenter=datacenter)
        # Set the announce message
        result.announce_message = ("dbctl restore of MediaWiki config (dc={dc}) from {f}").format(
            dc=datacenter if datacenter is not None else "all", f=file_object.name
        )
        return result

    def _write(self, config, datacenter=None):
        """Write the given config, if valid, to the datastore."""
        for dc, data in config.items():
            if datacenter is not None and dc != datacenter:
                continue
            errors = self._validate(config, datacenter)
            if errors:
                return ActionResult(False, 10, messages=errors)
            obj = self.entity(dc, DbConfig.object_name)
            obj.val = data
            obj.write()

        return ActionResult(True, 0)

    def _ask_confirmation(self, message, *, yes_responses=["y", "yes"]):
        """Display message to the user and prompt for confirmation, expecting yes_responses.

        Returns (success, error) where success is a boolean and error is a string.
        """
        if not sys.stdout.isatty():
            return (False, "Could not prompt for confirmation, stdin not a TTY.")

        print(message)
        prompt = "Enter {} to confirm: ".format(" or ".join(yes_responses))
        resp = input(prompt)

        if resp.lower() not in yes_responses:
            return (False, "User did not confirm")

        return (True, "")

    def _terminal_columns(self, minimum=100):
        """Get the number of columns on the user's tty, if any, or return minimum."""

        try:
            return max(minimum, os.get_terminal_size().columns)
        except OSError:
            return minimum

    def _check_section(self, name, section):
        """Checks the validity of a section in sectionLoads."""
        errors = []
        if not section[0]:
            errors.append("Section {} has no master".format(name))
        elif len(section[0]) != 1:
            errors.append(
                "Section {name} has multiple masters: {masters}".format(
                    name=name, masters=sorted(section[0].keys())
                )
            )

        return errors

    def _mw_section(self, section):
        """Translates the section name in the one expected by MediaWiki."""
        # Mangle the section key.
        # Thanks for this, MediaWiki
        if section == self.default_section:
            return "DEFAULT"
        else:
            return section
