import os
import logging
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
            except Exception as e:
                values[key] = self.get_default(key)
        return values

    def _set_value(self, key, validator, values):
        try:
            setattr(self, key, validator(values[key]))
        except Exception as e:
            # TODO: log validation error
            setattr(self, key, self.get_default(key))
