import collections
from conftool import yaml_safe_load


def get(configfile):
    """
    Loads the config from file
    """
    config = yaml_safe_load(configfile, default={})
    return Config(**config)


ConfigBase = collections.namedtuple('Config', [
    'driver',
    'hosts',
    'namespace',
    'api_version',
    'pools_path',
    'services_path',
    'driver_options',
    'tcpircbot_host',
    'tcpircbot_port',
    'cache_path',
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
                tcpircbot_host='',
                tcpircbot_port=0,
                cache_path='/var/cache/conftool'):

        if pools_path.startswith('/'):
            raise ValueError("pools_path must be a relative path.")
        if services_path.startswith('/'):
            raise ValueError("services_path must be a relative path.")

        return super().__new__(
            cls,
            driver=driver,
            hosts=hosts,
            namespace=namespace,
            api_version=api_version,
            pools_path=pools_path,
            services_path=services_path,
            driver_options=driver_options,
            tcpircbot_host=tcpircbot_host,
            tcpircbot_port=int(tcpircbot_port),
            cache_path=cache_path,
        )
