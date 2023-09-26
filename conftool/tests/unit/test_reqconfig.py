import argparse
from unicodedata import name
from unittest import mock

import pyparsing as pp
import pytest
from conftool import configuration, kvobject
from conftool.cli import ConftoolClient
from conftool.extensions.reqconfig import Requestctl, translate, SCHEMA
from conftool.tests.unit import MockBackend
from wmflib.interactive import AbortError


@pytest.fixture
def schema():
    """Return the reqestctl schema with a mock backend"""
    mock_schema = ConftoolClient(config=configuration.Config(driver=""), schema=SCHEMA).schema
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
    "to_parse,expected",
    [
        ("ipblock@cloud/gcp", ["ipblock@cloud/gcp"]),
        ("pattern@ua/requests", ["pattern@ua/requests"]),
        (
            "ipblock@cloud/gcp AND (pattern@ua/requests OR pattern@ua/curl)",
            ["ipblock@cloud/gcp", "AND", "(", "pattern@ua/requests", "OR", "pattern@ua/curl", ")"],
        ),
        (
            "ipblock@cloud/gcp AND NOT (pattern@ua/requests OR NOT pattern@ua/mediawiki)",
            [
                "ipblock@cloud/gcp",
                "AND NOT",
                "(",
                "pattern@ua/requests",
                "OR NOT",
                "pattern@ua/mediawiki",
                ")",
            ],
        ),
    ],
)
def test_grammar_good(requestctl, to_parse, expected):
    """Test grammar parses valid expressions."""
    assert requestctl._parse_and_check(to_parse) == expected


@pytest.mark.parametrize(
    "to_parse", ["pattern-ua/requests", "(pattern@query/nocache OR pattern@pages/wiki"]
)
def test_grammar_bad(requestctl, to_parse):
    """Test grammar rejects invalid expressions."""
    with pytest.raises(pp.ParseException):
        requestctl._parse_and_check(to_parse)


patterns = {
    "method/get": {"method": "GET"},
    "ua/unicorn": {"header": "User-Agent", "header_value": "^unicorn/"},
    "ua/curl": {"header": "User-Agent", "header_value": "^curl-\w"},
    "ua/requests": {"header": "User-Agent", "header_value": "^requests"},
    "url/page_index": {"url_path": "^/w/index.php", "query_parameter": "title", "method": "GET"},
    "req/no_accept": {"header": "Accept"},
    "req/body": {"method": "POST", "request_body": "foo"},
}


def mock_get_pattern(entity, slug):
    """Mock a request for a specific pattern."""
    obj = entity(*slug.split("/"))
    obj.from_net(patterns[slug])
    return obj


@pytest.mark.parametrize(
    "req,expected",
    [
        # Simple and with cloud
        (
            "pattern@ua/requests AND ipblock@cloud/gcp",
            'req.http.User-Agent ~ "^requests" && req.http.X-Public-Cloud ~ "^gcp$"',
        ),
        # And/or combination with parentheses, abuse ipblock
        (
            "ipblock@abuse/unicorn AND (pattern@ua/curl OR pattern@ua/requests)",
            'std.ip(req.http.X-Client-IP, "192.0.2.1") ~ unicorn && (req.http.User-Agent ~ "^curl-\\w" || req.http.User-Agent ~ "^requests")',
        ),
        # With negative conditions
        (
            "(pattern@ua/curl AND NOT pattern@ua/requests) AND NOT ipblock@abuse/unicorn",
            '(req.http.User-Agent ~ "^curl-\\w" && !(req.http.User-Agent ~ "^requests")) && std.ip(req.http.X-Client-IP, "192.0.2.1") !~ unicorn',
        ),
        # Negative conditions with parentheses
        (
            "ipblock@abuse/unicorn AND NOT (pattern@ua/curl OR pattern@ua/requests)",
            'std.ip(req.http.X-Client-IP, "192.0.2.1") ~ unicorn && !(req.http.User-Agent ~ "^curl-\\w" || req.http.User-Agent ~ "^requests")',
        ),
    ],
)
def test_vcl_from_expression(requestctl, req, expected):
    with mock.patch("conftool.extensions.reqconfig.translate.get_obj_from_slug") as get_obj:
        get_obj.side_effect = mock_get_pattern
        assert requestctl._vcl_from_expression(req) == expected


@pytest.mark.parametrize(
    "req, expected, negation",
    [
        ("method/get", 'req.method == "GET"', '!(req.method == "GET")'),
        ("ua/unicorn", 'req.http.User-Agent ~ "^unicorn/"', '!(req.http.User-Agent ~ "^unicorn/")'),
        (
            "url/page_index",
            '(req.method == "GET" && req.url ~ "^/w/index.php.*[?&]title")',
            '!(req.method == "GET" && req.url ~ "^/w/index.php.*[?&]title")',
        ),
        ("req/no_accept", "!req.http.Accept", "!(!req.http.Accept)"),
        ("req/body", 'req.method == "POST"', '!(req.method == "POST")'),
    ],
)
def test_vcl_from_pattern(requestctl, req, expected, negation):
    with mock.patch("conftool.extensions.reqconfig.translate.get_obj_from_slug") as get_obj:
        get_obj.side_effect = mock_get_pattern
        tr = translate.VCLTranslator(requestctl.schema)
        assert tr.from_pattern(req, False) == expected
        assert tr.from_pattern(req, True) == negation


def test_vcl_from_expression_bad_ipblock(requestctl):
    """An unsupported ipblock raises a readable issue"""
    vcl = translate.VCLTranslator(requestctl.schema)
    with pytest.raises(ValueError, match="scope 'pinkunicorn' is not currently supported"):
        vcl.from_ipblock("ipblock@pinkunicorn/somevalue", False)


@pytest.mark.parametrize(
    "path,param,value,expected",
    [
        ("/url", "", "", "/url"),
        ("", "title", "", "[?&]title"),
        ("", "title", "El-P", "[?&]title=El-P"),
        ("/url", "foo", "bar", "/url.*[?&]foo=bar"),
    ],
)
def test_url_match(requestctl, path, param, value, expected):
    tr = translate.VCLTranslator(requestctl.schema)
    assert tr._url_match(path, param, value) == f'req.url ~ "{expected}"'


@pytest.mark.parametrize(
    "req,expected",
    [
        # Simple and with cloud
        (
            "pattern@ua/unicorn AND ipblock@cloud/gcp",
            'ReqHeader:User-Agent ~ "^unicorn/" and ReqHeader:X-Public-Cloud ~ "^gcp$"',
        ),
        # And/or combination with parentheses, abuse ipblock
        (
            "ipblock@abuse/unicorn AND (pattern@ua/unicorn OR pattern@url/page_index)",
            'VCL_acl ~ "^MATCH unicorn.*" and (ReqHeader:User-Agent ~ "^unicorn/" or (ReqMethod ~ "GET" and ReqURL ~ "^/w/index.php.*[?&]title"))',
        ),
        # With negative conditions
        (
            "(pattern@ua/curl AND NOT pattern@ua/requests) AND NOT ipblock@abuse/unicorn",
            '(ReqHeader:User-Agent ~ "^curl-\\\\w" and not (ReqHeader:User-Agent ~ "^requests")) and VCL_acl ~ "^NO_MATCH unicorn"',
        ),
        # Negative conditions with parentheses
        (
            "ipblock@abuse/unicorn AND NOT (pattern@ua/curl OR pattern@ua/requests)",
            'VCL_acl ~ "^MATCH unicorn.*" and not (ReqHeader:User-Agent ~ "^curl-\\\\w" or ReqHeader:User-Agent ~ "^requests")',
        ),
    ],
)
def test_vsl_from_expression(requestctl, req, expected):
    with mock.patch("conftool.extensions.reqconfig.translate.get_obj_from_slug") as get_obj:
        get_obj.side_effect = mock_get_pattern
        assert requestctl._vsl_from_expression(req) == expected


@pytest.mark.parametrize(
    "req, expected, negation",
    [
        ("method/get", 'ReqMethod ~ "GET"', 'not (ReqMethod ~ "GET")'),
        (
            "ua/unicorn",
            'ReqHeader:User-Agent ~ "^unicorn/"',
            'not (ReqHeader:User-Agent ~ "^unicorn/")',
        ),
        (
            "url/page_index",
            '(ReqMethod ~ "GET" and ReqURL ~ "^/w/index.php.*[?&]title")',
            'not (ReqMethod ~ "GET" and ReqURL ~ "^/w/index.php.*[?&]title")',
        ),
        ("req/no_accept", "not ReqHeader:Accept", "not (not ReqHeader:Accept)"),
        ("req/body", 'ReqMethod ~ "POST"', 'not (ReqMethod ~ "POST")'),
    ],
)
def test_vsl_from_pattern(requestctl, req, expected, negation):
    with mock.patch("conftool.extensions.reqconfig.translate.get_obj_from_slug") as get_obj:
        get_obj.side_effect = mock_get_pattern
        tr = translate.VSLTranslator(requestctl.schema)
        assert tr.from_pattern(req, False) == expected
        assert tr.from_pattern(req, True) == negation


def test_confirm_diff(requestctl):
    with mock.patch("conftool.extensions.reqconfig.cli.ask_confirmation") as m:
        # Diff present, return true
        assert requestctl._confirm_diff("foo", "bar", "foobar")
        # no diff return false
        assert requestctl._confirm_diff("foo", "foo", "foobar") is False
        # Cancelled, return false
        m.side_effect = AbortError("test!")
        assert requestctl._confirm_diff("foo", "bar", "foobar") is False
