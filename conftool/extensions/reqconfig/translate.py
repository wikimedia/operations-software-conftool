from typing import List, Optional
from conftool.loader import Schema
from .schema import get_obj_from_slug


class DSLTranslator:
    """Abstract interface for a translator of our expression DSL."""

    pattern = "pattern@"
    ipblock = "ipblock@"
    # IPblocks implemented as ACLs
    acl_scopes = ["abuse"]
    custom_header_scopes = {"cloud": "X-Public-Cloud", "known-clients": "X-Known-Client"}
    # Translations.
    booleans = {"AND": None, "OR": None}
    parens = {"(": "(", ")": ")"}
    # the following translations are left blank here,as they change
    # Generic negation operator
    no = ""
    # Acl format string for matching ACLs
    acl = ""
    # Acl format string for non-matching ACLs
    no_acl = ""
    # Method selector
    method = ""
    # Url selector
    url = ""
    # Header selector prefix
    header_prefix = ""
    # Body selector. Set to None if body inspection is not supported.
    body: Optional[str] = ""
    # Equality operator. Sadly VSL doesn't have one so it will be overridden there.
    equality = "=="
    # Set to true if we need to escape backslashes
    escape_backslash = False

    def __init__(self, schema: Schema) -> None:
        self._pattern = schema.entities["pattern"]

    def from_expression(self, expression: List[str]) -> str:
        """Translate the expression."""
        translation = ""
        negation = False
        for token in expression:
            # detect negation
            if token.endswith(" NOT"):
                negation = True
                # TODO: use removesuffix once we're on python >= 3.9 only
                token = token[:-4]
            if token in self.booleans:
                translation += self.booleans[token]
            elif token in self.parens:
                if negation:
                    translation += f"{self.no}"
                    negation = False
                translation += self.parens[token]
            elif self._is_pattern(token):
                translation += self.from_pattern(token, negation)
                negation = False
            elif self._is_ipblock(token):
                translation += self.from_ipblock(token, negation)
                negation = False
        return translation

    def _is_pattern(self, token: str) -> bool:
        return token.startswith(self.pattern)

    def _is_ipblock(self, token: str) -> bool:
        return token.startswith(self.ipblock)

    def from_ipblock(self, ipblock: str, negation: bool) -> str:
        """Translate an ipblock to specific rules."""
        slug = ipblock.replace(self.ipblock, "")
        scope, value = slug.split("/")
        if scope in self.acl_scopes:
            if negation:
                return self.no_acl.format(value=value)
            else:
                return self.acl.format(value=value)
        elif scope in self.custom_header_scopes:
            oper = "~"
            if negation:
                oper = "!~"
            return f'{self.header_prefix}{self.custom_header_scopes[scope]} {oper} "^{value}$"'
        else:
            raise ValueError(f"scope '{scope}' is not currently supported")

    def _escape(self, expr: str) -> str:
        """Escape a regex, if needed."""
        if self.escape_backslash:
            return expr.replace("\\", "\\\\")
        else:
            return expr

    def from_pattern(self, pattern: str, negation: bool) -> str:
        output = []
        slug = pattern.replace(self.pattern, "")
        obj = get_obj_from_slug(self._pattern, slug)
        if obj.method:
            output.append(f'{self.method} {self.equality} "{obj.method}"')
        url_rule = self._url_match(
            self._escape(obj.url_path), obj.query_parameter, self._escape(obj.query_parameter_value)
        )
        if url_rule != "":
            output.append(url_rule)
        if obj.header:
            if obj.header_value:
                output.append(
                    f'{self.header_prefix}{obj.header} ~ "{self._escape(obj.header_value)}"'
                )
            # Header with no value means absence of the header
            else:
                output.append(f"{self.no}{self.header_prefix}{obj.header}")
        # Do not add a request_body filter to anything but POST.
        # If this inspection is not supported in the translation set self.body to None
        if obj.request_body and obj.method == "POST" and self.body is not None:
            output.append(f'{self.body} ~ "{obj.request_body}"')
        if len(output) > 1 or negation:
            joined = self.booleans["AND"].join(output)
            if negation:
                return f"{self.no}({joined})"
            else:
                return f"({joined})"
        else:
            return output.pop()

    def _url_match(self, url: str, param: str, value: str) -> str:
        """Return the query corresponding to the pattern."""
        if not any([url, param, value]):
            return ""
        out = f'{self.url} ~ "'
        if url != "":
            out += url
            if param != "":
                out += ".*"
        if param != "":
            out += f"[?&]{param}"
            if value != "":
                out += f"={value}"
        # close the quotes
        out += '"'
        return out


class VSLTranslator(DSLTranslator):
    """Translates expressions to VSL."""

    booleans = {"AND": " and ", "OR": " or "}
    parens = {"(": "(", ")": ")"}
    # the following translations are left blank here,as they change
    # Generic negation operator. Please note the needed trailing whitespace
    no = "not "
    # Acl format string for matching ACLs
    acl = 'VCL_acl ~ "^MATCH {value}.*"'
    # Acl format string for non-matching ACLs
    no_acl = 'VCL_acl ~ "^NO_MATCH {value}"'
    # Method selector
    method = "ReqMethod"
    # Url selector
    url = "ReqURL"
    # Header selector prefix
    header_prefix = "ReqHeader:"
    # Body selector
    body = None
    # escape backslash
    escape_backslash = True
    # No equal sign in VSL
    equality = "~"


class VCLTranslator(DSLTranslator):
    """Translates expressions to VSL."""

    booleans = {"AND": " && ", "OR": " || "}
    parens = {"(": "(", ")": ")"}
    # the following translations are left blank here,as they change
    # Generic negation operator.
    no = "!"
    # Acl format string for matching ACLs
    acl = 'std.ip(req.http.X-Client-IP, "192.0.2.1") ~ {value}'
    # Acl format string for non-matching ACLs
    no_acl = 'std.ip(req.http.X-Client-IP, "192.0.2.1") !~ {value}'
    # Method selector
    method = "req.method"
    # Url selector
    url = "req.url"
    # Header selector prefix
    header_prefix = "req.http."
    # Body selector is not supported in varnish minus,
    # but only in the non-free version via the bodyaccess vmod.
    body = None
