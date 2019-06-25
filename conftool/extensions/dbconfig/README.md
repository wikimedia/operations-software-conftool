Database Management (for MediaWiki and beyond)
----------------------------------------------

The WMF stores configuration in etcd that is written/modified by conftool and
read from MediaWiki as part of its configuration, under the object type
`mwconfig`. `dbconfig` is a conftool extension that allows to easily manage such
configuration. Its command line tool is called `dbctl` (trust me or not, there
is no reference in the name to the CICS tool of the same name).

`dbctl` manages 3 types of objects:
* The variables directly read by MediaWiki (via `dbctl config`)
* The information about database sections and their metadata (via `dbctl
  section`)
* The information about database instances, which sections they're part of, and
  their state (via `dbctl instance`)

The variables read by MediaWiki are calculated by dbctl from the other two
object types, and saved to etcd for MediaWiki consumption. This allows us to
create "transactions" for submitting the configuration, rather than having to
commit each single change in a sequence.

So, say you want to depool a database instance from all sections, you just need
to do something along the lines of what follows:

    # verify the current status
    dbctl instance db1:3307 get
    # set it to depooled. This still doesn't affect MediaWiki
    dbctl instance db1:3307 depool
    # Now let's commit this change to the MediaWiki configuration
    dbctl config commit
    # Let's check the new config is what we wanted
    dbctl config get | jq .test.sectionLoads.s1


Until you `commit` the configuration change, MediaWiki will not see any of your
actions.

At each step in your procedures, the resulting configuration will be checked for
mistakes, and any change that would make the configuration invalid is rejected
before writing to the datastore.

Let's now get into the details of how `dbctl` works:

### Section objects

The sections are organized by datacenter, so you will have to indicate it when
accessing objects or results could be ambiguous.

A section object has the following properties:

* `master` the name of the database instance that is the master for this
  section.
* `min_replicas` (integer) minimum number of replicas acceptable for this section
* `readonly` (boolean) if the section should be set to read-only or not
* `reason` The reason for the read-only state, if any

You can interact with section objects with `dbctl` as follows:

#### Getting data about a section

To get the content of a section object, you can simply do

    dbctl --scope dc1 section s1 get

The special section `all` can be used to show all sections at once, with or
without specifying the `-s/--scope` parameter.

#### Changing the master

When you change the master, the new instance reference needs to be a valid,
configured database instance, or our safeguards will prevent you from changing
the master database. In the future, more checks could be added (like only
allowing changing the master if the section is already in readonly
mode). Assuming `db1:3309` is an instance object, a typical syntax will be:

    dbctl --scope dc1 section s1 set-master db1:3309

as usual, the new configuration will not take effect until you commit it.

#### Setting the section readonly (readwrite)

Read-only:

    dbctl --scope dc2 section s1 ro "Some reason"

Read-write:

    dbctl --scope dc2 section s1 rw

#### Editing a new record

When you add a new section to your datastore, via `conftool-sync`, it will be
unconfigured and will NOT appear in the final configuration of the system.

When you need to edit the full record of a section, the `edit` subcommand shall
be used. You can override the editor to use by setting the EDITOR environment
variable

    dbctl --scope dc3 section s1 edit


### Instance objects

Instances are organized by datacenter as well, and might be configured for
multiple sections. An instance object contains the following properties:

* `host_ip` the ipv4 or ipv6 address of the instance
* `port` the TCP port of the instance
* `sections` a dictionary of configurations for the sections this instance belongs
  to; the keys of this dictionary are the sections configured for this instance.

The values of the `sections` dictionary are composed as follows:

* `pooled` (boolean) the pooled/depooled state of the instance in this specific
  section. This setting overrides any pooled status set later in the
  groups settings if set to false
* `percentage` (integer between 0 and 100) a multiplier for the weight, that
  allows to progressively pool/depool a server without changing its predefined
  weight. This applies to all the weights.
* `weight` (integer) the nominal weight of the server for this section. The
  effective weight in the configuration will be the product of this value by the
  percentage listed above. Of course the nominal weight can be set to 0, even if
  the percentage is not set to 0.
* `groups` a dictionary of configurations (if any) for the special usage groups for
  this section. The name of the special usage groups are the keys of this dictionary.

The elements of the `groups` dictionary are composed as follows:

* `pooled` (boolean) the pooled/depooled state of the instance within this
  group. Please note that properly, the server will be pooled in this special
  group only if the value of this field is true, and the value of the main
  `pooled` variable of the section is true as well.
* `weight` (integer) the weight of the server for this special usage group. The
  effective weight in the configuration will be the product of this value by the
  percentage listed above

#### Example instance in yaml format

    # tags: datacenter = dc1, name = db2:3308
    host_ip: 192.168.1.12
    port: 3308
    sections:
        s1: {pooled: true, weight: 10, percentage: 100}
        s2:
            pooled: true
            weight: 1
            percentage: 50
            groups:
                dump:
                    pooled: false
                    weight: 0
                logpager:
                    pooled: true
                    weight: 1

You can interact with instance objects using `dbctl` as follows:

#### Getting data about an instance
To obtain the data about an instance, you can just search it by name (the scope is just optional)

    dbctl instance db1 get

#### Depooling an instance

You can specify which parts of the configuration to act on, and you can either depool the whole instance from all sections, or from one specific section, or finally from a specific group within a section.

    # Depool globally
    dbctl instance db1 depool
    # Depool one section
    dbctl instance db1 depool --section s1
    # Depool one specific group
    dbctl instance db1 depool --section s2 --group logpager

#### Pooling an instance

Pooling works pretty much like depooling, with one difference: you can declare a "pooling percentage", that will determine which fraction of the nominal weight of the instance will be used.

    # Pool all, at nominal weight
    dbctl instance db1 pool
    # Pool all, at 10% the nominal weight
    dbctl instance db1 pool -p 10
    # You can also define a section and a group
    dbctl instance db1 pool -p 20 --section s2 --group logpager

#### Changing weights

Changing the weight of an instance to a new value is pretty easy:

    # Set the main weight for s1
    dbctl instance db2:3308 set-weight 10 --section s1
    # Set the weight for a group
    dbctl instance db2:3308 set-weight 1 --section s2 --group logpager

### MediaWiki-related records

MediaWiki can fetch configuration variables from a specific etcd path; dbctl integrates with that mechanism and provides 3 variables per datacenter for MediaWiki consumption:

* `sectionLoads` which contains information about the pools of databases dedicated to the various section_master
* `groupLoadsBySection` which contains the same information for specific usage groups
* `readOnlyBySection` which contains all sections (if any) which are supposed to be in read-only mode

#### Reading your current live configuration

To see the currently-live configuration used by MediaWiki, just do:

    dbctl config get

#### Displaying the configuration computed from scratch

To see the configuration as it would be generated from the underlying instance and section objects:

    dbctl config generate

This will print the generated configuration to stdout, print any errors in validating the configuration to stderr,
and exit with 0 on no errors.

#### Diff between currently-live and computed-from-scratch configuration

To show the diff between the configuration that is live, and what would be generated from the underlying instance and section objects:

    dbctl config diff

TODO: In the future, this will exit with status code 0 on identical configurations, exit code 1 on diffs, and other codes on error.

This command also accepts a `-q`/`--quiet` argument, which suppresses diff output, useful in scripts or conditionals.

#### Synchronizing your changes

These variables are calculated from the sum of all the initialized instances and sections that have been created, and synced upon issue of the commit command

    # Commit configuration changes to be read by MediaWiki
    dbctl config commit

What will happen once you call commit is what follows:

* All instances and sections are read from the datastore.
* A configuration based on those data is computed.
* This configuration gets sanity-checked according to rules we implemented: at the time of this writing, we just verify there is a master, and that the minimum number of replicas is present.  (These three steps are also the `generate` command.)
* A diff is shown, and the user is prompted for confirmation.
* A backup copy of the previous configuration is saved locally to disk and the rollback command printed to stderr.
* Once the new configuration is considered valid, it is atomically written to the datastore and is available for MediaWiki to consume.


#### Rollback a change

In case a new configuration causes issues and a quick rollback is needed, just execute the rollback
command printed to stderr when committing.

    # Restore the configuration from file
    dbctl config restore /path/to/previous_config.json

The file will be read, validated and writted to the datastore to make it available for MediaWiki to consume.
The internal section and instance objects will not be touched, so a new `dbctl config commit` whould re-apply
the configuration from before the restore.
