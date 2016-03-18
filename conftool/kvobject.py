import os
import json
from contextlib import contextmanager
from conftool import _log, backend, drivers


class KVObject(object):
    backend = None
    config = None
    _schema = {}

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
    def base_path(self):
        raise NotImplementedError("All kvstore objects should implement this")

    @property
    def key(self):
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
            return self._from_net(None)
        except drivers.BackendError as e:
            _log.error("Backend error while fetching %s: %s", self.key, e)
            # TODO: maybe catch the backend errors separately
            return None
        self._from_net(values)

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

    def _from_net(self, values):
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
        try:
            setattr(self, key, validator(values[key]))
        except Exception as e:
            _log.info("Value for key %s is invalid: %s",
                      key, e)
            if set_defaults:
                val = self.get_default(key)
                _log.warn("Setting %s to the default value %s",
                          key, val)
                setattr(self, key, val)
            else:
                _log.warn("Not setting a value")

    def __str__(self):
        d = {self.name: self._to_net()}
        d['tags'] = self.tags
        return json.dumps(d)
