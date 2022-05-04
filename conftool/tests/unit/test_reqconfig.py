import argparse
from unicodedata import name
import pytest
import pyparsing as pp

from unittest import mock

from conftool import configuration, kvobject
from conftool.extensions.reqconfig import get_schema, Requestctl
from conftool.extensions.reqconfig.cli import vcl_url_match
from conftool.tests.unit import MockBackend


@pytest.fixture
def schema():
    """Return the reqestctl schema with a mock backend"""
    mock_schema = get_schema(configuration.Config(driver=""))
    # Now overload the backend.
    kvobject.KVObject.backend = MockBackend({})
    return mock_schema


@pytest.fixture
def requestctl():
    args = argparse.Namespace(debug=True, config=None, command="commit")
    # We need to patch validate_pattern and validate_ipblock early, before we actually build the object.
    with mock.patch(
        "conftool.extensions.reqconfig.Requestctl._validate_pattern"
    ) as val, mock.patch("conftool.extensions.reqconfig.Requestctl._validate_ipblock") as ipb:
        ipb.return_value = None
        val.return_value = None
        req = Requestctl(args)
        kvobject.KVObject.backend = MockBackend({})
        kvobject.KVObject.config = configuration.Config(driver="")

    return req


@pytest.mark.parametrize(
    "to_parse",
    [
        "ipblock@cloud/gcp",
        "pattern@ua/requests",
        "ipblock@cloud/gcp AND (pattern@ua/requests OR pattern@ua/curl)",
    ],
)
def test_grammar_good(requestctl, to_parse):
    """Test grammar parses valid expressions."""
    requestctl._parse_and_check(to_parse)


@pytest.mark.parametrize(
    "to_parse", ["pattern-ua/requests", "(pattern@query/nocache OR pattern@pages/wiki"]
)
def test_grammar_bad(requestctl, to_parse):
    """Test grammar rejects invalid expressions."""
    with pytest.raises(pp.ParseException):
        requestctl._parse_and_check(to_parse)


@pytest.mark.parametrize(
    "expr,expected",
    [
        # Simple and with cloud
        (
            "pattern@ua/requests AND ipblock@cloud/gcp",
            'requests && req.http.X-Public-Cloud ~ "gcp"',
        ),
        # And/or combination with parentheses, abuse ipblock
        (
            "ipblock@abuse/unicorn AND (pattern@ua/curl OR pattern@ua/requests)",
            'std.ip(req.http.X-Client-IP, "192.0.2.1") ~ unicorn && (curl || requests)',
        ),
    ],
)
def test_vcl_from_expression(requestctl, expr, expected):
    vcl_patterns = {"ua/requests": "requests", "ua/curl": "curl"}
    requestctl._vcl_from_pattern = lambda slug: vcl_patterns[slug]
    assert requestctl._vcl_from_expression(expr) == expected


patterns = {
    "method/get": {"method": "GET"},
    "ua/unicorn": {"header": "User-Agent", "header_value": "^unicorn/"},
    "url/page_index": {"url_path": "^/w/index.php", "query_parameter": "title", "method": "GET"},
}


@pytest.mark.parametrize(
    "req,expected",
    [
        ("method/get", 'req.method == "GET"'),
        ("ua/unicorn", 'req.http.User-Agent ~ "^unicorn/"'),
        ("url/page_index", '(req.method == "GET" && req.url ~ "^/w/index.php.*[?&]title")'),
    ],
)
def test_vcl_from_pattern(requestctl, req, expected):
    with mock.patch("conftool.extensions.reqconfig.cli.get_obj_from_slug") as get_obj:
        to_return = requestctl.schema.entities["pattern"](*req.split("/"))
        to_return.from_net(patterns[req])
        get_obj.return_value = to_return
        assert requestctl._vcl_from_pattern(req) == expected


@pytest.mark.parametrize(
    "path,param,value,expected",
    [
        ("/url", "", "", "/url"),
        ("", "title", "", "[?&]title"),
        ("", "title", "El-P", "[?&]title=El-P"),
        ("/url", "foo", "bar", "/url.*[?&]foo=bar"),
    ],
)
def test_vcl_url_match(path, param, value, expected):
    assert vcl_url_match(path, param, value) == f'req.url ~ "{expected}"'
