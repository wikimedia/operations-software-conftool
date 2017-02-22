import argparse
import functools
import glob
import logging
import os
import sys

import yaml

from conftool import _log, configuration, loader
from conftool.kvobject import KVObject
from conftool.drivers import BackendError


# Generic exception handling decorator
def catch_and_log(log_msg):
    def actual_wrapper(fn):
        @functools.wraps(fn)
        def _catch(*args, **kwdargs):
            try:
                return fn(*args, **kwdargs)
            except BackendError as e:
                _log.error("%s Backend %s: %s", fn.__name__,
                           log_msg, e)
            except Exception as e:
                _log.critical("%s generic %s: %s", fn.__name__,
                              log_msg, e)
                raise
        return _catch
    return actual_wrapper


class Syncer(object):

    def __init__(self, schema_file, base_path):
        self.load_order = []
        self.schema = loader.Schema.from_file(schema_file)
        self.base_path = base_path

    def add(self, name, entity, dep_chain=None):
        """ Adds a class to the syncing list resolving its dependencies"""
        if dep_chain is None:
            dep_chain = []
        # Check if we're re-adding an already inserted entity
        _log.debug("Adding %s, dep_chain %s", name, dep_chain)
        if not dep_chain and name in self.load_order:
            _log.debug("%s already added, skipping", name)
            return
        # Try to detect circular dependencies
        dep_chain.append(name)
        for dependency in entity.depends:
            _log.debug("Adding dependency %s first", dependency)
            if dependency in dep_chain:
                # this is a circular dependency, it is fatal
                raise ValueError("Dependency loop: %s=>%s" %
                                 ("=>".join(dep_chain), dependency))
            if dependency in self.load_order:
                # this is already in the list of dependencies, we can bail out
                continue
            self.add(dependency, self.schema.entities[dependency],
                     dep_chain=dep_chain)
        self.load_order.append(name)

    def load(self):
        """
        Load all the entities from file and sync
        """
        if self.schema.has_errors:
            raise ValueError("Schema is broken, NOT loading data.")
        syncers = {}
        # load the files and Create the load order
        for name, cls in self.schema.entities.items():
            cls = self.schema.entities[name]
            syncers[name] = EntitySyncer(name, cls)
            syncers[name].load_files(self.base_path)
            self.add(name, cls, [])

        for name in self.load_order:
            _log.info("Adding objects for %s", name)
            sync = syncers[name]
            try:
                sync.load()
            except Exception as e:
                _log.error("Loading of data for entity %s failed: %s", name, e)
                sync.skip_removal = True

        # Now let's cleanup in reverse order
        self.load_order.reverse()
        for name in self.load_order:
            _log.info("Removing stale objects for %s", name)
            syncers[name].cleanup()


class EntitySyncer(object):

    def __init__(self, name, cls):
        self.entity = name
        self.cls = cls
        self.to_remove = []
        self.data = {}
        self.skip_removal = False

    def load_files(self, rootdir):
        entity_path = os.path.join(rootdir, self.entity)
        _log.info("Loading data for entity %s from %s", self.entity, rootdir)
        if not os.path.isdir(entity_path):
            _log.error("Data dir %s does not exist, will NOT remove missing entities", entity_path)
            self.skip_removal = True
        for filename in glob.glob(os.path.join(entity_path, '*.yaml')):
            with open(filename, 'rb') as fh:
                _log.info("Parsing file %s", filename)
                try:
                    filedata = yaml.load(fh)
                except:
                    _log.critical("Malformed data in file %s",
                                  filename)
                    filedata = {}
                    self.skip_removal = True

            try:
                exp_data = self.cls.from_yaml(filedata)
                self.data.update(exp_data)
            except Exception:
                _log.critical(
                    "Data in file %s could not be loaded",
                    self.data, exc_info=True)
                self.skip_removal = True

    def load(self):
        # Now we have all the data, let's translate those to tags/entities
        to_load, self.to_remove = self.get_changes(self.data)
        for key in to_load:
            tags = key.split('/')
            _log.debug("Loading %s:%s", self.entity, key)
            obj = self.cls(*tags)
            if obj.static_values:
                _log.info("Syncing static object %s:%s", self.entity, key)
                obj.from_net(self.data[key])
            else:
                if obj.exists:
                    # For some reason, the object already exists, do nothing
                    _log.warning("Not loading %s:%s: object already exists")
                    continue
                else:
                    _log.info("Creating %s with tags %s", self.entity, key)
            obj.write()

    def cleanup(self):
        if self.skip_removal:
            if self.to_remove:
                _log.info(
                    "Not removing %s objects %s: errors processing files",
                    self.entity, self.to_remove)
            return
        for key in self.to_remove:
            tags = key.split('/')
            obj = self.cls(*tags)
            if obj.exists:
                _log.info("Removing %s with tags %s", self.entity, key)
                obj.delete()

    def get_changes(self, exp_data):
        try:
            live_data = dict(self.cls.backend.driver.all_data(
                self.cls.base_path()))
        except ValueError as e:
            # Empty remote server
            # TODO: Generalize and move to the etcd driver this hack.
            if str(e).endswith('is not a directory'):
                live_data = {}
            else:
                raise
        exp_set = set(exp_data.keys())
        live_set = set(live_data.keys())
        new = exp_set - live_set
        to_remove = live_set - exp_set
        # If this entity is static, load changed values as well
        to_change = set()
        if self.cls.static_values:
            to_change = {el for el in (live_set & exp_set) if live_data[el] != exp_data[el]}

        return (new | to_change, to_remove)


def get_args(args):
    parser = argparse.ArgumentParser(description="Tool to sync the declared "
                                     "configuration on-disk with the kvstore "
                                     "data")
    parser.add_argument('--directory',
                        help="Directory containing the files to sync")
    parser.add_argument('--config', help="Optional configuration file",
                        default="/etc/conftool/config.yaml")
    parser.add_argument('--debug', action="store_true",
                        default=False, help="print debug info")
    parser.add_argument(
        '--schema', default="/etc/conftool/schema.yaml",
        help="Schema file that defines additional object types"
    )
    return parser.parse_args(args)


def main(arguments=None):
    if arguments is None:
        arguments = sys.argv[1:]

    args = get_args(arguments)

    if args.debug:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    logging.basicConfig(
        level=log_level,
        format='%(asctime)s [%(levelname)s] %(name)s::%(funcName)s: %(message)s',
        datefmt='%F %T'
    )

    try:
        c = configuration.get(args.config)
        KVObject.setup(c)
    except Exception as e:
        _log.critical("Invalid configuration: %s", e)
        sys.exit(1)

    if not os.path.isdir(args.directory):
        _log.critical("Could not find directory %s", args.directory)
        sys.exit(2)

    sync = Syncer(args.schema, args.directory)
    sync.load()
