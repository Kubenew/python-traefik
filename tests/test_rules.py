"""Tests for rule parsing — Host, PathPrefix, Path, &&, ||, parentheses, new matchers."""
import pytest
from starlette.requests import Request

from python_traefik.rules import parse_rule


def _make_request(
    host: str = "example.com",
    path: str = "/",
    method: str = "GET",
    headers: list | None = None,
    client: tuple = ("127.0.0.1", 12345),
) -> Request:
    """Build a minimal ASGI Request for testing."""
    raw_headers = [(b"host", host.encode())]
    if headers:
        for k, v in headers:
            raw_headers.append((k.encode() if isinstance(k, str) else k,
                                v.encode() if isinstance(v, str) else v))
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": raw_headers,
        "query_string": b"",
        "server": ("127.0.0.1", 8000),
        "client": client,
        "scheme": "http",
    }
    return Request(scope)


# --- Single matchers ---

def test_host_rule():
    rule = parse_rule("Host(`example.com`)")
    assert rule.matcher(_make_request(host="example.com")) is True
    assert rule.matcher(_make_request(host="other.com")) is False


def test_host_case_insensitive():
    rule = parse_rule("Host(`Example.COM`)")
    assert rule.matcher(_make_request(host="example.com")) is True


def test_host_with_port():
    rule = parse_rule("Host(`example.com`)")
    assert rule.matcher(_make_request(host="example.com:8000")) is True


def test_pathprefix_rule():
    rule = parse_rule("PathPrefix(`/api`)")
    assert rule.matcher(_make_request(path="/api/users")) is True
    assert rule.matcher(_make_request(path="/other")) is False


def test_path_exact_rule():
    rule = parse_rule("Path(`/health`)")
    assert rule.matcher(_make_request(path="/health")) is True
    assert rule.matcher(_make_request(path="/health/extra")) is False


def test_method_rule():
    rule = parse_rule("Method(`POST`)")
    assert rule.matcher(_make_request(method="POST")) is True
    assert rule.matcher(_make_request(method="GET")) is False


def test_headers_rule():
    rule = parse_rule("Headers(`x-custom`, `hello`)")
    assert rule.matcher(_make_request(headers=[("x-custom", "hello")])) is True
    assert rule.matcher(_make_request(headers=[("x-custom", "other")])) is False
    assert rule.matcher(_make_request()) is False


def test_hostregexp_rule():
    rule = parse_rule(r"HostRegexp(`^.*\.example\.com$`)")
    assert rule.matcher(_make_request(host="api.example.com")) is True
    assert rule.matcher(_make_request(host="example.com")) is False


def test_clientip_exact():
    rule = parse_rule("ClientIP(`10.0.0.1`)")
    assert rule.matcher(_make_request(client=("10.0.0.1", 9999))) is True
    assert rule.matcher(_make_request(client=("10.0.0.2", 9999))) is False


def test_clientip_cidr():
    rule = parse_rule("ClientIP(`192.168.1.0/24`)")
    assert rule.matcher(_make_request(client=("192.168.1.50", 9999))) is True
    assert rule.matcher(_make_request(client=("10.0.0.1", 9999))) is False


# --- Compound rules ---

def test_and_rule():
    rule = parse_rule("Host(`example.com`) && PathPrefix(`/api`)")
    assert rule.matcher(_make_request(host="example.com", path="/api/v1")) is True
    assert rule.matcher(_make_request(host="other.com", path="/api/v1")) is False
    assert rule.matcher(_make_request(host="example.com", path="/other")) is False


def test_or_rule():
    rule = parse_rule("Host(`a.com`) || Host(`b.com`)")
    assert rule.matcher(_make_request(host="a.com")) is True
    assert rule.matcher(_make_request(host="b.com")) is True
    assert rule.matcher(_make_request(host="c.com")) is False


def test_parenthesised_rule():
    rule = parse_rule("(Host(`a.com`) || Host(`b.com`)) && PathPrefix(`/api`)")
    assert rule.matcher(_make_request(host="a.com", path="/api/x")) is True
    assert rule.matcher(_make_request(host="b.com", path="/api/x")) is True
    assert rule.matcher(_make_request(host="a.com", path="/other")) is False
    assert rule.matcher(_make_request(host="c.com", path="/api/x")) is False


# --- Edge cases ---

def test_unsupported_rule_raises():
    with pytest.raises(ValueError, match="Unsupported rule expression"):
        parse_rule("Bogus(`value`)")


def test_empty_rule_raises():
    with pytest.raises(ValueError):
        parse_rule("")
