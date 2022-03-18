Http request control
--------------------

The WMF stores configuration in etcd that is written/modified by conftool and
read from confd and finally translated to VCL that gets loaded by varnish.

We load the following things from etcd into the varnish configuration:
* The list of pooled ats backends to connect to in the same datacenter
* The list of IP ranges for every public cloud, in the form of a netmapper file
* A list of rate-limiting/ban rules for incoming traffic.

`requestctl` is a conftool extension that allows to easily manage the latter
two types of data. It manages 3 types of objects:
* `pattern` objects describe specific patterns of an HTTP request
* `ipblock` objects group specific IP ranges that pertain to a single logical
  group, so for example the ipblock with scope=cloud,name=aws includes all the
  IP ranges used by AWS.
* `action` objects describe an action to be performed on a request matching
  specific combinations of patterns and ipblocks.

`requestctl` allows you to edit the data you want to store in etcd in a
directory tree, and to `sync` such data to the datastore, and to also `dump` the
directory tree corresponding to the current state of the datastore.
Additionally, it allows you to `get` a peek into what is live in the datastore,
and to `enable` or `disable` actions based on that.

On a given varnish host, we will have:
* One vcl condition per *enabled* `action` defined for the cluster the host is
  in, on the condition that either the action is enabled for all datacenters or
  it's enabled for the specific datacenter we're in.
* A netmapper file containing all the `ipblock` entries defined under the
  *cloud* scope
* A vcl list of ACLs, one for each `ipblock` entry under the *abuse* scope

For more information about the object model, see the section below.
### requestctl get
Gets the data from the datastore and displays them in the desired format.
Can be used to fetch all objects or just one.

Examples:
```bash
  $ requestctl get pattern
  +------------------------+-------------------------------+
  |          name          |            pattern            |
  +------------------------+-------------------------------+
  |   cache-text/docroot   |          url:^/[\?$]          |
  | cache-text/bad_param_q |           ?q=\w{12}           |
  |   cache-text/enwiki    |    Host: en.wikipedia.org     |
  |  cache-text/restbase   |      url:^/api/rest_v1/       |
  | cache-text/action_api  |        url:/w/api.php         |
  | cache-text/requests_ua | User-Agent: python-requests.* |
  |  cache-text/wiki_page  |     url:/wiki/[^:]+(\?$)      |
  |      ua/requests       | User-Agent: ^python-requests  |
  +------------------------+-------------------------------+



  $ requestctl get pattern ua/requests -o json | jq .
  {
    "ua/requests": {
      "method": "",
      "request_body": "",
      "url_path": "",
      "header": "User-Agent",
      "header_value": "^python-requests",
      "query_parameter": "",
      "query_parameter_value": ""
    }
  }

  $ requestctl get pattern ua/requests -o yaml
  ua/requests:
    header: User-Agent
    header_value: ^python-requests
    method: ''
    query_parameter: ''
    query_parameter_value: ''
    request_body: ''
    url_path: ''

```

### requestctl sync/dump
For each category of objects, you can sync from a specific repository, like follows:

```bash
# This is actually ~ copying the directory tree, via etcd
$ requestctl sync -g base_dir action [-i] [--purge]
$ requestctl dump -g dump_dir action
```

Here the command line parameters mean:
* `-g`, `--git-repo` identifies the base directory
* `-i`, `--interactive` (sync only) indicates if we want to be prompted before
  any write/delete operation happens
* `-p`, `--purge` if we want to delete stale entries from the datastore.
The purge operation should be considered generally omitted for anything but actions, and should be done only when explicitly removing an object. `requestctl` will not allow you to remove a pattern/ipblock if they're still referenced in an action.

The structure of the directory tree should contain one file per object we want to
upload to the datastore, with path as follows:
```
<root>/request-{ipblocks,actions/patterns}/<tag>/<name>.yaml
```

### requestctl enable/disable
Enable / disable actions (the `enabled` field in actions is explicitly excluded from syncing).
```bash
$ requestctl enable cache-text/foobar  # enables cache-text/foobar
$ requestctl disable cache-text/foobar # disables the same action.
```


## Object Model
We don't use the shared conftool schema for reqconfig, but rather a specialized schema contained in `conftool.extensions.reqconfig.cli.SCHEMA`.
### Pattern
A pattern object should be able to describe, with good flexibility, the large majority
of the characteristics we want to match in a request.

Each pattern has an associated "scope" tag. The fields of each record are:
* `method`, the http method
* `request_body` a regex to match in the http body. CURRENTLY UNSUPPORTED IN VARNISH.
* `url_path` the path part of the url, will be used as a regexp
* `header` an header name to match, using the regexp at `header_value`;
* `header_value` the regexp to match the value of `header` to. If left blank
  when a header is defined, the pattern means "the header is not present"
* `query_parameter` and `query_parameter_value` are a parameter and a regexp for
  the value of a query parameter to match. An empty value will be interpreted as
  "for any value".

### Ipblock
The ipblock object is very simple: it has an associated scope tag (which has
semantic value, see above), a name and just two fields:
* `comment`: a comment to describe what is the intended use of an ipblock
* `cidrs`: a list of network ranges in CIDR notation.

### Action
An action object has two main functions: describing a composition of patterns
and ipblocks to form a request pattern that we want to manage, and a description
of the actions we will take on matching requests.

The objects are associated to a specific *cluster* (`cache-text` or
`cache-upload` at the time of writing) and have a name. Their fields are as follows:
* `enabled` boolean. If false, the pattern will *not* be included in VCL
* `sites` a list of datacenters where to apply the rule. If empty, the rule will
  be applied to all datacenters.
* `cache_miss_only` boolean. If false, the pattern will be applied *also* to cache hits. CURRENTLY ONLY CACHE MISSES ARE CONSIDERED
* `comment` a comment to describe what this action does.
* `expression` a string describing the combination of patterns and ipblocks that
  should be matched. The BNF of the grammar is described in
  `cli.Requestctl.grammar`, but in short:
  * A pattern is referenced with the keyword `pattern@<scope>/<name>`
  * An ipblock is referenced with the keyword `ipblock@<scope>/<name>`
  * patterns and ipblocks can be combined with `AND` and `OR` logic and groups
    can be organized using parentheses

  So for example, a valid expression could look like:
  ```
  ( pattern@ua/requests OR pattern@ua/curl ) AND ipblock@cloud/aws
    AND pattern@site/commons
  ```
* `resp_status` the http status code to send as a response
* `resp_reason` the text to send as a reason with the response
* `do_throttle` boolean to say if we should throttle requests matching the
  `expression` (true) on just respond with `resp_status` unconditionally (false)
* `throttle_requests`, `throttle_interval`, `throttle_duration` are the three
  arguments of `vsthrottle` in VCL to control the rate-limiting behaviour.
* `throttle_per_ip` boolean makes the rate-limiting per-ip rather than
  per-cache-server

### Use as library
```python
from conftool.extensions.reqconfig import get_schema
from conftool import configuration

# we assume aws_ip_blocks contains a list of CIDRs
schema = get_schema(configuration.get(CONFIG_FILE))
aws = schema.entities["ipblock"]("cloud", "aws")
aws.update({'comment': 'aws', 'cidrs': aws_ip_blocks})
```