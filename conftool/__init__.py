import os
import logging
import json
from conftool import backend
from conftool import drivers

_log = logging.getLogger(__name__)


class KVObject(object):
    backend = None
    config = None
    _schema = {}

    @classmethod
    def setup(cls, configobj):
        cls.config = configobj
        cls.backend = backend.Backend(cls.config)

    def kvpath(self, *args):
        return os.path.join(self.base_path, *args)

    @property
    def key(self):
        raise NotImplementedError("All kvstore objects should implement this")

    @property
    def name(self):
        return os.path.basename(self.key)

    def get_default(self, what):
        raise NotImplementedError("All kvstore objects should implement this.")

    def fetch(self):
        self.exists = False
        try:
            values = self.backend.driver.read(self.key)
            if values:
                self.exists = True
        except drivers.BackendError:
            # TODO: maybe catch the backend errors separately
            # TODO: log errors
            return None
        self._from_net(values)

    def write(self):
        return self.backend.driver.write(self.key, self._to_net())

    def delete(self):
        self.backend.driver.delete(self.key)

    @classmethod
    def get_tags(cls, taglist):
        tuplestrip = lambda tup: tuple(map(lambda x: x.strip(), tup))
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
        except Exception:
            # TODO: log validation error
            if set_defaults:
                setattr(self, key, self.get_default(key))

    def __str__(self):
        d = {self.name: self._to_net()}
        return json.dumps(d)
