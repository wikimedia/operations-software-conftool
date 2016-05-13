import yaml
import collections
from conftool import _log


def get(configfile):
    """
    Loads the config from file
    """
    try:
        with open(configfile, 'rb') as fh:
            config = yaml.load(fh.read())
    except Exception as e:
        _log.error('Could not load file %s: %s',
                   configfile, e)
        config = {}

    return Config(**config)


ConfigBase = collections.namedtuple('Config', ['driver', 'hosts',
                                               'namespace',
                                               'api_version',
                                               'pools_path',
                                               'services_path',
                                               'driver_options',
                                               'tcpircbot_host',
                                               'tcpircbot_port'
                                               ])


class Config(ConfigBase):

    def __new__(cls,
                driver='etcd',
                hosts=['http://localhost:2379'],
                namespace='/conftool',
                api_version='v1',
                pools_path='pools',
                services_path='services',
                driver_options={},
                tcpircbot_host='localhost',
                tcpircbot_port='9999'
                ):
        if pools_path.startswith('/'):
            raise ValueError("pools_path must be a relative path.")
        if services_path.startswith('/'):
            raise ValueError("services_path must be a relative path.")

        return super(Config, cls).__new__(cls, driver=driver,
                                          hosts=hosts,
                                          namespace=namespace,
                                          api_version=api_version,
                                          pools_path=pools_path,
                                          services_path=services_path,
                                          driver_options=driver_options,
                                          tcpircbot_host=tcpircbot_host,
                                          tcpircbot_port=int(tcpircbot_port))
