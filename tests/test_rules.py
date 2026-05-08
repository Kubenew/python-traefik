from starlette.requests import Request
from starlette.datastructures import Headers
from starlette.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from python_traefik.rules import parse_rule


def test_host_rule():
    rule = parse_rule("Host(`example.com`)")
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"host", b"example.com")],
        "query_string": b"",
        "server": ("127.0.0.1", 8000),
        "client": ("127.0.0.1", 12345),
        "scheme": "http",
    }
    req = Request(scope)
    assert rule.matcher(req) is True


def test_pathprefix_rule():
    rule = parse_rule("PathPrefix(`/api`)")
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/users",
        "headers": [(b"host", b"example.com")],
        "query_string": b"",
        "server": ("127.0.0.1", 8000),
        "client": ("127.0.0.1", 12345),
        "scheme": "http",
    }
    req = Request(scope)
    assert rule.matcher(req) is True
