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

There is an additional derived data type, called `vcl`, which is generated automatically
when the `requestctl commit` command is issued. This is what gets then injected into
varnish.

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
* Possibly more netmapper files for things like crawlers.

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

### requestctl validate
Validate objects written in a repository, useful for CI:
```bash
$ requestctl validate base_dir
$
```
It will exit with non-zero exit status if any error is present.

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

### requestctl log
Output the varnishncsa command to run on a cache host to see requests matching our action.
```bash
$ requestctl log cache-text/requests_ua_api

You can monitor requests matching this action using the following command:
sudo varnishncsa -n frontend -g request \
  -F '"%{X-Client-IP}i" %l %u %t "%r" %s %b "%{Referer}i" "%{User-agent}i" "%{X-Public-Cloud}i"' \
  -q 'ReqHeader:User-Agent ~ "^python-requests" and ( ReqURL ~ "^/api/rest_v1/" or ReqURL ~ "/w/api.php" ) and  not VCL_ACL eq "MATCH wikimedia_nets"'

```

### requestctl vcl
Output the vcl fragment generated from the action.
```bash
$ requestctl vcl cache-text/requests_ua_api

// FILTER requests_ua_api
// Disallow python-requests to access restbase or the action api
// This filter is generated from data in etcd. To disable it, run the following command:
// sudo requestctl disable 'cache-text/requests_ua_api'
if (req.http.User-Agent ~ "^python-requests" && (req.url ~ "^/api/rest_v1/" || req.url ~ "/w/api.php") && vsthrottle.is_denied("requestctl:requests_ua_api", 500, 30s, 1000s)) {
    return (synth(429, "Please see our UA policy"));
}

```

### requestctl commit
Commit changes to actions to the compiled vcl datastore. By default it's interactive, you need to pass `-b` if you want to run in batch mode.
```
$ requestctl enable cache-text/requests_ua_api
$ requestctl commit
--- cache-text/global.old

+++ cache-text/global.new

@@ -1,3 +1,12 @@

+
+// FILTER requests_ua_api
+// Disallow python-requests to access restbase or the action api
+// This filter is generated from data in etcd. To disable it, run the following command:
+// sudo requestctl disable 'cache-text/requests_ua_api'
+if (req.http.User-Agent ~ "^python-requests" && (req.url ~ "^/api/rest_v1/" || req.url ~ "/w/api.php") && vsthrottle.is_denied("requestctl:requests_ua_api", 500, 30s, 1000s)) {
+    set req.http.Requestctl = req.http.Requestctl + ",requests_ua_api";
+    return (synth(429, "Please see our UA policy"));
+}
+

 // FILTER enwiki_api_cloud
 // Limit access to the enwiki api from the clouds

==> Ok to commit these changes?
Type "go" to proceed or "abort" to interrupt the execution
>
```

### requestctl find
You can find which actions include a specific pattern/ipblock using the find command:
```bash
$ requestctl find ua/requests
action: generic_ua_aws, expression: (pattern@ua/requests OR pattern@ua/curl) AND ipblock@cloud/aws
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
  * patterns and ipblocks can be combined with `AND`/`AND NOT` and `OR`/`OR NOT` logic and groups
    can be organized using parentheses.

  So for example, a valid expression could look like:
  ```
  ( pattern@ua/requests OR pattern@ua/curl ) AND ipblock@cloud/aws
    AND  NOT pattern@site/commons
  ```
* `resp_status` the http status code to send as a response
* `resp_reason` the text to send as a reason with the response
* `do_throttle` boolean to say if we should throttle requests matching the
  `expression` (true) on just respond with `resp_status` unconditionally (false)
* `throttle_requests`, `throttle_interval`, `throttle_duration` are the three
  arguments of `vsthrottle` in VCL to control the rate-limiting behaviour.
* `throttle_per_ip` boolean makes the rate-limiting per-ip rather than
  per-cache-server
* `log_matching` if true, it will record in X-Requestctl if a request matches the rule. It will thus be included
  into the `vcl` objects even if disabled; it will just not perform any banning / ratelimiting action.

### Use as library
```python
from conftool.extensions.reqconfig import get_schema
from conftool import configuration

# we assume aws_ip_blocks contains a list of CIDRs
schema = get_schema(configuration.get(CONFIG_FILE))
aws = schema.entities["ipblock"]("cloud", "aws")
aws.update({'comment': 'aws', 'cidrs': aws_ip_blocks})
```