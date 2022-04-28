"""Views for requestctl."""
import json
import textwrap
from string import Template
from typing import Dict, List

import tabulate
import yaml
from conftool.kvobject import Entity


def get(fmt: str) -> "View":
    """Factory method to get a view class.

    Typical use: reqconfig.view.get("json").render(data)
    """
    if fmt == "json":
        return JsonView
    elif fmt == "yaml":
        return YamlView
    elif fmt == "pretty":
        return PrettyView
    elif fmt == "vcl":
        return VCLView
    elif fmt == "vsl":
        return VSLView
    else:
        raise ValueError(f"Unsupported format '{format}'")


class View:
    """Abstract view interface"""

    @classmethod
    def render(cls, data: List[Entity], object_type: str) -> str:
        """Renders the view."""


class YamlView(View):
    """Yaml representation of our objects."""

    @classmethod
    def dump(cls, data: List[Entity]) -> Dict[str, Dict]:
        """Create a easily-human-readable dump of the data."""
        dump = {}
        for entity in data:
            asdict = entity.asdict()
            dump[entity.pprint()] = asdict[entity.name]
        return dump

    @classmethod
    def render(cls, data: List[Entity], _: str) -> str:
        return yaml.dump(cls.dump(data))


class JsonView(YamlView):
    """Json representation of our objects."""

    @classmethod
    def render(cls, data: List[Entity], _: str) -> str:
        return json.dumps(cls.dump(data))


class PrettyView(View):
    """Pretty-print information about the selected entitites."""

    headers = {
        "pattern": ["name", "pattern"],
        "ipblock": ["name", "cidrs"],
        "action": ["name", "action", "response", "throttle"],
    }

    @classmethod
    def render(cls, data: List[Entity], object_type: str) -> str:
        headers = cls.headers[object_type]
        tabular = []
        for entity in data:
            if object_type == "pattern":
                element = (entity.pprint(), cls.get_pattern(entity))
            elif object_type == "ipblock":
                element = (entity.pprint(), "\n".join(entity.cidrs))
            elif object_type == "action":
                element = (
                    textwrap.shorten(entity.pprint(), width=30),
                    textwrap.fill(entity.expression, width=30),
                    textwrap.shorten(f"{entity.resp_status} {entity.resp_reason}", width=20),
                    str(entity.do_throttle).lower(),
                )
            tabular.append(element)
        return tabulate.tabulate(tabular, headers, tablefmt="pretty")

    @classmethod
    def get_pattern(cls, entity: Entity) -> str:
        """String representation of a pattern"""
        out = []
        if entity.method:
            out.append(entity.method)
        if entity.url_path:
            out.append(f"url:{entity.url_path}")
        if entity.header:
            out.append(f"{entity.header}: {entity.header_value}")
        if entity.query_parameter:
            out.append(f"?{entity.query_parameter}={entity.query_parameter_value}")
        return "\n".join(out)


class VCLView(View):
    """Renders an action as VCL."""

    tpl_ban = Template(
        """
// FILTER $name
// $comment
// This filter is generated from data in $driver. To disable it, run the following command:
// sudo requestctl disable '$pprint'
if ($expression) {
    set resp.http.X-Requestctl = resp.http.X-Requestctl + ",$name";
    return (synth($status, "$reason"));
}
"""
    )
    tpl_throttle = Template(
        """
// FILTER $name
// $comment
// This filter is generated from data in $driver. To disable it, run the following command:
// sudo requestctl disable '$pprint'
if ($expression && $throttle) {
    set resp.http.X-Requestctl = resp.http.X-Requestctl + ",$name";
    return (synth($status, "$reason"));
}
"""
    )
    tpl_log_only = Template(
        """
// FILTER $name
// $comment
// This filter is DISABLED. to enable it, run the following command:
// sudo requestctl enable '$pprint'
if ($expression) {
    set resp.http.X-Requestctl = resp.http.X-Requestctl + ",$name";
}
"""
    )
    header = """
// Set the header to the empty string if not present.
if (!resp.http.X-Requestctl) {
    set resp.http.X-Requestctl = "";
}
"""
    footer = """
// Remove the comma at the start of the line, if present.
set resp.http.X-Requestctl = regsub(resp.http.X-Requestctl, "^,", "");
"""

    @classmethod
    def render(cls, data: List[Entity], _: str = "") -> str:
        out = [cls.header]
        for action in sorted(data, key=lambda k: k.name):
            # TODO: Check vcl_expression is there?
            substitutions = dict(
                name=action.name,
                comment=action.comment,
                pprint=action.pprint(),
                reason=action.resp_reason,
                status=action.resp_status,
                expression=action.vcl_expression,
                driver="etcd",  # TODO: get this from configuration
            )
            if action.do_throttle:
                substitutions["throttle"] = cls.get_throttle(action)
                out.append(cls.tpl_throttle.substitute(substitutions))
            else:
                out.append(cls.tpl_ban.substitute(substitutions))
        out.append(cls.footer)
        return "\n".join(out)

    @classmethod
    def get_throttle(cls, action: Entity) -> str:
        """Throttle rule for an action."""
        key = f'"requestctl:{action.name}"'
        if action.throttle_per_ip:
            key = f'"requestctl:{action.name}:" + req.http.X-Client-IP'
        args = [
            key,
            str(action.throttle_requests),
            f"{action.throttle_interval}s",
            f"{action.throttle_duration}s",
        ]
        return f"vsthrottle.is_denied({', '.join(args)})"


class VSLView(View):
    """Outputs the varnishlog command to match requests corresponding to an action."""

    tpl_log = Template(
        """
You can monitor requests matching this action using the following command:
sudo varnishncsa -n frontend -g request \\
  -F '"%{X-Client-IP}i" %l %u %t "%r" %s %b "%{Referer}i" "%{User-agent}i" "%{X-Public-Cloud}i"' \\
  -q '$vsl and VCL_ACL eq "NO_MATCH wikimedia_nets"'
"""
    )

    @classmethod
    def render(cls, data: List[Entity], _: str = "") -> str:
        return cls.tpl_log.substitute(vsl=data[0].vsl_expression)
