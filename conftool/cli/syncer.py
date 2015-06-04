# TODO: logging
from conftool import KVObject, configuration, _log
from collections import defaultdict
from conftool import node, service
from conftool.drivers import BackendError
import argparse
import sys
import yaml
import os
import functools
import logging


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


def get_service_actions(cluster, data):
    exp_services = set(data.keys())
    try:
        cl_dir = service.Service.dir(cluster)
        services = dict(KVObject.backend.driver.ls(cl_dir))
    except ValueError:
        services = {}
    act_services = set(services.keys())
    del_services = act_services - exp_services
    new_services = exp_services - act_services
    changed_services = set([el for el in (act_services & exp_services)
                            if services[el] != data[el]])
    _log.debug("Changed services in cluster %s: %s", cluster,
               " ".join(changed_services))
    _log.debug("New services in cluster %s: %s", cluster,
               " ".join(new_services))
    _log.debug("Services to remove in cluster %s: %s", cluster,
               " ".join(del_services))
    return (new_services | changed_services, del_services)


@catch_and_log("error while loading services")
def load_service(cluster, servname, servdata):
    s = service.Service(cluster, servname)
    s._from_net(servdata)
    s.write()


def load_services(cluster, servnames, data):
    # TODO: logs, exceptions
    for servname in servnames:
        _log.info("Loading service %s/%s", cluster, servname)
        servdata = data[servname]
        load_service(cluster, servname, servdata)


@catch_and_log("error while deleting services")
def remove_services(cluster, servnames):
    for servname in servnames:
        s = service.Service(cluster, servname)
        if s.exists:
            _log.info("Removing service %s/%s", cluster, servname)
            s.delete()


@catch_and_log("error while calculating changed nodes")
def get_changed_nodes(dc, cluster, servname, expected_hosts):
    s = service.Service(cluster, servname)
    if not s.exists:
        _log.warning("Service %s not found, skipping", servname)
        return ([], [])
    host_set = set(expected_hosts)
    service_dir = node.Node.dir(dc, cluster, servname)
    try:
        cur_nodes = KVObject.backend.driver.ls(service_dir)
    except ValueError:
        cur_nodes = []
    cur_hosts = set([el[0] for el in cur_nodes])
    new_nodes = host_set - cur_hosts
    del_nodes = cur_hosts - host_set
    return (new_nodes, del_nodes)


@catch_and_log("error while loading node")
def load_node(dc, cluster, servname, host):
    n = node.Node(dc, cluster, servname, host)
    if not n.exists:
        _log.debug("Creating node %s for cluster %s/%s", host,
                   cluster, servname)
        n.write()


@catch_and_log("error while deleting node")
def delete_node(dc, cluster, servname, host):
    n = node.Node(dc, cluster, servname, host)
    if n.exists:
        _log.debug("Removing node %s from cluster %s/%s", host,
                   cluster, servname)
        n.delete()


def load_nodes(dc, data):
    # Read data and arrange them in the form we expect
    for cluster, cl_data in data.items():
        cl = defaultdict(list)
        for host, services in cl_data.items():
            for servname in services:
                cl[servname].append(host)
        for servname, hosts in cl.items():
            new_nodes, del_nodes = get_changed_nodes(dc, cluster,
                                                     servname, hosts)
            for el in new_nodes:
                _log.debug("See if %s is present", el)
                load_node(dc, cluster, servname, el)
            for el in del_nodes:
                _log.debug("See if %s should be deleted", el)
                delete_node(dc, cluster, servname, el)


def tag_files(directory):
    def tag(d, path, files):
        tag = path.replace(directory, '').lstrip('/')
        if not tag:
            return
        real_files = [os.path.realpath(os.path.join(path, f)) for f in files]
        d[tag].extend(real_files)
    tagged = defaultdict(list)
    os.path.walk(directory, tag, tagged)
    return tagged

def get_args(args):
    parser = argparse.ArgumentParser(description="Tool to sync the declared "
                                     "configuration on-disk with the kvstore "
                                     "data")
    parser.add_argument('--directory', help="Directory containing the files to sync")
    parser.add_argument('--config', help="Configuration file")
    return parser.parse_args(args)


def main(arguments=None):
    if arguments is None:
        arguments = list(sys.argv)
        arguments.pop(0)

    args = get_args(arguments)
    logging.basicConfig(level=logging.DEBUG)
    try:
        c = configuration.get(args.config)
        KVObject.setup(c)
    except Exception as e:
        raise
        _log.critical("Invalid configuration: %s", e)
        sys.exit(1)
    files = tag_files(args.directory)
    # Load services data.
    # TODO: This must be fixed to be less specific
    if files['services']:
        service_file = files['services'][0]
        with open(service_file, 'rb') as fh:
            servdata = yaml.load(fh)
    else:
        servdata = {}
    # Refresh services:
    rem = {}
    for cluster, data in servdata.items():
        load, rem[cluster] = get_service_actions(cluster, data)
        load_services(cluster, load, data)
    # sync nodes
    for filename in files['nodes']:
        dc = os.path.basename(filename).rstrip('.yaml')
        with open(filename, 'rb') as fh:
            dc_data = yaml.load(fh)
        load_nodes(dc, dc_data)
    # Now delete services
    for cluster, servnames in rem.items():
        remove_services(cluster, servnames)
