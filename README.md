Wikimedia conftool
=======================

[![Build Status](https://travis-ci.org/wikimedia/operations-software-conftool.svg?branch=master)](https://travis-ci.org/wikimedia/operations-software-conftool)
[![Coverage Status](https://coveralls.io/repos/github/wikimedia/operations-software-conftool/badge.svg?branch=master)](https://coveralls.io/github/wikimedia/operations-software-conftool?branch=master)

Conftool is a tool for storing configuration
objects with associated tags into a remote k-v store.

Currently only an etcd backend is implemented, but the tool is
designed so that adding additional backends shouldn't be too hard.

Installation
------------

    python setup.py install

Configuration
-------------

The default config file for `conftool` is located at
`/etc/conftool/config.yaml`; it can be changed via a command-line
switch, `--config`. The following configurations can be changed:

* `driver` (default: 'etcd'): the driver to use. At the moment, only an
  etcd driver is available

* `hosts` (default: ['http://localhost:2379']): a list of hosts to
  connect to, available for the driver to use.

* `namespace` (default: '/conftool'): the basic key namespace in the
  k-v backend

* `api_version` (default: 'v1'): an api versioning token that allows
  for seamless schema changes

* `pools_path` (default: 'pools'): base path for the 'node' entity

* `services_path` (default: 'services'): base path for the 'service' entity

* `driver_options` (default: {}): a dict of options to pass to the
  specific driver you're using. Check the specific driver class for
  details.

* `tcpircbot_host` host to connect to to announce to the IRC bot what
  we're doing

* `tcpircbot_port` port to connect to to announce to the IRC bot what
  we're doing

Usage
-----

Conftool is based on the idea that a basic configuration structure is
held in yaml files that are synced to the kv store via a cli tool
called `conftool-sync`, but the values within each config object can be
fetched (and changed) dinamically using `confctl`.

Objects that conftool can treat are managed via a schema file; details
about schema files syntax can be found in the dedicated section.

Each type of objects has a set of tags associated with it; for example,
the 'node' object (that is used to describe a server/service within a
pool) has the following tags associated with it: dc (datacenter),
cluster (the cluster of machines), service (the specific service),
plus the fqdn of the node as the object name. In general, tags are
used so that it's easy for you (or applications) to retreive/modify
objects in the store. The values of the objects will not be touched by
the syncing process.

`confctl` allows to find objects and view, modify and delete objects.

There are three ways to find objects:

* via a tag selector:

        confctl select 'foo=PATTERN,fizz=PATTERN,...,name=PATTERN' (get|set/k=v:k1=v1...,del)

  this is by far the most powerful method: it allows to find any object with a
  selection of matching tags and name; if any label is omitted, it is discarded
  in the selection process. New users should typically use this method, as it's
  much more powerful than the other two

* via a full list of tags and a namedef:

        confctl tags foo=TAG,bar=TAG,fizz=TAG --action (get|set/k=v:k1=v1...,del) NAMEDEF

  where namedef is either the node name or a regex in the form re:PATTERN. It
  will act on any node matching said pattern, with those specific tags. A
  special NAMEDEF is 'all', which will make conftool act on all the objects
  corresponding to the listed tags. This method is most convenient when acting
  on a single object (say by depooling a service when it is restarted), because
  it's more optimized than the other ones (typically needs one query to the backend
  instead than doing expensive recursive queries).

you can also set the values from a yaml file instead of the command line,
which could be useful whenever you find yourself manipulating complex
fields like dictionaries or lists, by just using the action `set/@filename`.

Finally, you can edit a full record by using the action `edit`.

Defining a schema
-----------------

A schema can be defined in a yaml file, in the form

    ENTITY_NAME:
      path: PATH
      tags: [TAG1,TAG2,...]
      schema:
        FIELD1:
          type: "string"
          default: "DEFAULT1"
        FIELD2:
          type: "enum:yes|no|inactive"
          default: "inactive"
        ...
      depends:
        - OTHER_ENTITY
      free_form: false
      json_schema:
        base_path: PATH_ON_DISK
        rules:
          RULE1:
            schema: sometype.schema
            selector: TAG1=VAL1,TAG2=REGEX
          RULE2:
            schema: othertype.schema
            selector: TAG1=VAL1,TAG2=REGEX

here, ENTITY_NAME is the name of the object type, as indicated on the
command line via the `--object-type ENTITY_NAME` switch. Every object
type has a path in the k/v store path-like key we're using, identified
by the PATH variable. Every object of this type will have the listed
tags (TAG1, TAG2, ...) attached to them.

Within the `schema` key we have the list of the fields of the object,
with their associated types. Supported types at the moment include:

* `string`
* `int`
* `list`
* `dict`
* `enum:CHOICEA|CHOICHEB|...` an enumeration of allowed values

Since the object type can reference another object type, there is the
possibility to indicate a dependency, although at the moment automatic
reference and storage of relationship is only supported for builtin
object types.

Finally, `free_form` determines if only predefined fields are accepted
(when `false`, the default) or if additional fields can be added to an
object.

It is also possible to define more fine-grained controls on the structure
of an object by defining its structure via a json schema. If you want to do
that, you will have to add a reference in your main schema to the additional
validation you want to provide in the `json_schema` section. There you can
declare rules in the form shown above - all the ones whose `selector` matches
the current objects will be applied, and the schema indicated in the `schema`
stanza will be used for validation.

So for instance if you define

    horse:
      path: "horses"
      tags:
        - color
        - breed
      schema:
        height:
          default: 0
        nick:
          default: ''
        custom:
          default: null
      json_schema:
        base_path: "schemas"
        rules:
          running_horses:
            schema: 'runner_horse.schema'
            selector: "breed=runner"

you will check any `horse` object with tag `breed=runner` with the JSON schema that
can be found in `schemas/runner_horse.schema`. This allows for better granularity and precision of your data validation.



Running tests
-------------

To run the integration tests, you will need to install `etcd` on your machine.

We use the `tox` utility, a wrapper around virtualenv. To list available
environements:

    tox -l

To run one:

    tox -e flake8

You can pass extra arguments to the underlying command, for example to only run
the unit tests:

    tox -e py27 -- --test-suite conftool.tests.unit
