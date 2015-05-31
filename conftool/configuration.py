import yaml
import collections


def get(configfile):
    """
    Loads the config from file
    """
    try:
        with open(configfile, 'rb') as fh:
            config = yaml.load(fh.read())
    except Exception as e:
        # TODO log something
        config = {}

    return Config(**config)

ConfigBase = collections.namedtuple('Config', ['driver', 'hosts',
                                               'namespace',
                                               'pools_path',
                                               'services_path',
                                               ])


class Config(ConfigBase):
    def __new__(cls,
                driver='etcd',
                hosts=['http://localhost:2379'],
                namespace='/conftool',
                pools_path='pools',
                services_path='services'
                ):
        if pools_path.startswith('/'):
            raise ValueError("pools_path must be a relative path.")
        if services_path.startswith('/'):
            raise ValueError("services_path must be a relative path.")

        return super(Config, cls).__new__(cls, driver=driver,
                                          hosts=hosts,
                                          namespace=namespace,
                                          pools_path=pools_path,
                                          services_path=services_path)
