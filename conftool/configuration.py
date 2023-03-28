import collections
from conftool import yaml_safe_load


class ConfigurationError(Exception):
    """Exception raised when we fail to load the configuration."""


def get(configfile):
    """
    Loads the config from file
    """
    try:
        config = yaml_safe_load(configfile, default={})
        return Config(**config)
    except Exception as exc:
        raise ConfigurationError(exc) from exc


ConfigBase = collections.namedtuple(
    "Config",
    [
        "driver",
        "hosts",
        "namespace",
        "api_version",
        "pools_path",
        "driver_options",
        "tcpircbot_host",
        "tcpircbot_port",
        "cache_path",
    ],
)


class Config(ConfigBase):
    def __new__(
        cls,
        driver="etcd",
        hosts=["http://localhost:2379"],
        namespace="/conftool",
        api_version="v1",
        pools_path="pools",
        driver_options={},
        tcpircbot_host="",
        tcpircbot_port=0,
        cache_path="/var/cache/conftool",
    ):
        if pools_path.startswith("/"):
            raise ValueError("pools_path must be a relative path.")

        return super().__new__(
            cls,
            driver=driver,
            hosts=hosts,
            namespace=namespace,
            api_version=api_version,
            pools_path=pools_path,
            driver_options=driver_options,
            tcpircbot_host=tcpircbot_host,
            tcpircbot_port=int(tcpircbot_port),
            cache_path=cache_path,
        )
