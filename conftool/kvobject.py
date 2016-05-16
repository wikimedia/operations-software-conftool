import json
import os

from collections import OrderedDict
from contextlib import contextmanager

from conftool import _log, backend, drivers


class KVObject(object):
    backend = None
    config = None
    _schema = {}
    static_values = False

    @classmethod
    def setup(cls, configobj):
        cls.config = configobj
        cls.backend = backend.Backend(cls.config)

    def kvpath(self, *args):
        return os.path.join(self.base_path(), *args)

    @classmethod
    def find(cls, name):
        """Generator of a list of objects for a given name"""
        for tags in cls.backend.driver.find_in_path(cls.base_path(), name):
            yield cls(*tags)

    @classmethod
    def query(cls, query):
        """
        Return all matching object given a tag:regexp dictionary as a query

        If any tag (or the object name) are omitted, all of them are supposed to
        get selected.
        """
        tags = cls._tags + ['name']
        for labels in cls.backend.driver.all_keys(cls.base_path()):
            is_matching = True
            for i, tag in enumerate(tags):
                regex = query.get(tag, None)
                if regex is None:
                    # Label selector not specified, we catch anything
                    continue
                if not regex.match(labels[i]):
                    _log.debug("label %s did not match regex %s", labels[i],
                               regex.pattern)
                    is_matching = False
                    break
            if is_matching:
                yield cls(*labels)

    @classmethod
    def base_path(cls):
        raise NotImplementedError("All kvstore objects should implement this")

    @property
    def key(self):
        raise NotImplementedError("All kvstore objects should implement this")

    @property
    def dir(self):
        raise NotImplementedError("All kvstore objects should implement this")

    @property
    def name(self):
        return os.path.basename(self.key)

    @property
    def tags(self):
        """Returns a dict of the current tags"""
        res = {}
        # The current key, minus the basepath, is the list of tags +
        # the node name
        tags = self.key.replace(
            self.base_path(), '').lstrip('/').split('/')[:-1]
        for i in range(len(self._tags)):
            res[self._tags[i]] = tags[i]
        return res

    def get_default(self, what):
        raise NotImplementedError("All kvstore objects should implement this.")

    def fetch(self):
        self.exists = False
        try:
            values = self.backend.driver.read(self.key)
            if values:
                self.exists = True
        except drivers.NotFoundError:
            return self.from_net(None)
        except drivers.BackendError as e:
            _log.error("Backend error while fetching %s: %s", self.key, e)
            # TODO: maybe catch the backend errors separately
            return None
        self.from_net(values)

    def write(self):
        return self.backend.driver.write(self.key, self._to_net())

    def delete(self):
        self.backend.driver.delete(self.key)

    @classmethod
    def parse_tags(cls, taglist):
        """Given a taglist as a string, return an ordered list of tags"""
        def tuplestrip(tup):
            return tuple(map(lambda x: x.strip(), tup))
        tagdict = dict([tuplestrip(el.split('=')) for el in taglist])
        # will raise a KeyError if not all tags are matched
        return [tagdict[t] for t in cls._tags]

    def update(self, values):
        """
        Update values of properties in the schema
        """
        for k, v in values.items():
            if k not in self._schema:
                continue
            self._set_value(k, self._schema[k], {k: v}, set_defaults=False)
        self.write()

    @classmethod
    def from_yaml(cls, data):
        if cls.static_values:
            return cls._kv_from_yaml(data)
        else:
            return cls._from_yaml(data)

    @classmethod
    def _kv_from_yaml(cls, data):
        """Get keys and values from the yaml file"""
        depth = len(cls._tags)
        if depth == 0:
            return data
        # Flatten a multidimensional dict
        # to {a/b/c/d: val} format
        while depth > 0:
            depth -= 1
            tmpdict = {}
            for k, v in data.items():
                tmpdict.update({("%s/%s" % (k, el)): val for el, val in v.items()})
            data = tmpdict
        return data

    @classmethod
    def _from_yaml(cls, data):
        depth = len(cls._tags)
        if depth == 0:
            return {el: None for el in data}
        while depth > 1:
            depth -= 1
            tmpdict = {}
            for k, v in data.items():
                tmpdict.update({("%s/%s" % (k, el)): val for el, val in v.items()})
            data = tmpdict
        tmpdict = {}
        for tags, names in data.items():
            tmpdict.update(
                dict([("%s/%s" % (tags, name), None) for name in names]))
        return tmpdict

    @classmethod
    @contextmanager
    def lock(cls, path):
        try:
            l = cls.backend.driver.get_lock(path)
            yield l
            cls.backend.driver.release_lock(path)
        except Exception as e:
            _log.critical("Problems inside lock for %s: %s", path, e)
            cls.backend.driver.release_lock(path)
            raise
        except (SystemExit, KeyboardInterrupt) as e:
            _log.critical("Aborted.")
            cls.backend.driver.release_lock(path)

    def from_net(self, values):
        """
        Fetch the values from the kvstore into the object
        """
        for key, validator in self._schema.items():
            self._set_value(key, validator, values)

    def _to_net(self):
        values = {}
        for key in self._schema.keys():
            try:
                values[key] = getattr(self, key)
            except Exception:
                values[key] = self.get_default(key)
        return values

    def _set_value(self, key, validator, values, set_defaults=True):
        # When initializing a object, we don't really care
        # about logging warnings
        if values is None:
            if set_defaults:
                setattr(self, key, self.get_default(key))
            return

        try:
            setattr(self, key, validator(values[key]))
        except Exception as e:
            _log.info("Value for key %s is invalid: %s",
                      key, e, exc_info=True)
            if set_defaults:
                val = self.get_default(key)
                _log.warn("Setting %s to the default value %s",
                          key, val)
                setattr(self, key, val)
            else:
                _log.warn("Not setting a value")

    def __str__(self):
        d = OrderedDict()
        d[self.name] = self._to_net()
        tags = self.tags
        d['tags'] = ','.join(["%s=%s" % (k, tags[k]) for k in self._tags])
        return json.dumps(d)

    def __eq__(self, obj):
        return (self.__class__ == obj.__class__ and
                self.name == obj.name and
                self.tags == obj.tags and
                self._to_net() == obj._to_net())


class Entity(KVObject):
    """
    General-purpose entity with a strict schema
    """
    depends = []

    def __init__(self, *tags):
        if len(tags) != (len(self._tags) + 1):
            raise ValueError(
                "Need %s as tags, %s provided",
                ",".join(self._tags),
                ",".join(tags[:-1]))

        self._name = tags[-1]
        self._key = self.kvpath(*tags)
        self._current_tags = {}
        for i, tag in enumerate(self._tags):
            self._current_tags[tag] = tags[i]
        self.fetch()
        self._defaults = {}

    @property
    def key(self):
        return self._key

    @property
    def tags(self):
        return self._current_tags

    @classmethod
    def dir(cls, *tags):
        if len(tags) != len(cls._tags):
            raise ValueError("Need %s as tags, %s provided",
                             ",".join(cls._tags),
                             ",".join(tags))
        return os.path.join(cls.base_path(), *tags)


class FreeSchemaEntity(Entity):

    def __init__(self, *tags, **kwargs):
        self._schemaless = kwargs
        super(FreeSchemaEntity, self).__init__(*tags)

    def _to_net(self):
        values = super(FreeSchemaEntity, self)._to_net()
        for k, v in self._schemaless.items():
            values[k] = v
        return values

    def from_net(self, values):
        super(FreeSchemaEntity, self).from_net(values)
        if values is None:
            return
        for key, value in values.items():
            if key not in self._schema:
                self._schemaless[key] = value

    def changed(self, data):
        return self._to_net() != data
