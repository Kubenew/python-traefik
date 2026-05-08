"""Tests for the proxy module — header filtering, X-Forwarded-* injection."""
import pytest
from starlette.requests import Request

from python_traefik.proxy import _filter_headers, _inject_forwarded_headers


def _make_request(
    host: str = "example.com",
    scheme: str = "http",
    client: tuple = ("10.0.0.1", 12345),
) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/test",
        "headers": [(b"host", host.encode())],
        "query_string": b"",
        "server": ("127.0.0.1", 8000),
        "client": client,
        "scheme": scheme,
    })


def test_filter_hop_by_hop():
    headers = {
        "host": "example.com",
        "connection": "keep-alive",
        "content-type": "text/html",
        "transfer-encoding": "chunked",
        "x-custom": "value",
    }
    filtered = _filter_headers(headers)
    assert "connection" not in filtered
    assert "transfer-encoding" not in filtered
    assert "host" in filtered
    assert "content-type" in filtered
    assert "x-custom" in filtered


def test_inject_forwarded_headers():
    req = _make_request(host="example.com", scheme="http", client=("10.0.0.1", 12345))
    headers = {"host": "example.com", "accept": "text/html"}
    result = _inject_forwarded_headers(req, headers)
    assert result["x-forwarded-for"] == "10.0.0.1"
    assert result["x-forwarded-host"] == "example.com"
    assert result["x-forwarded-proto"] == "http"
    # Original headers preserved
    assert result["accept"] == "text/html"


def test_inject_forwarded_appends():
    """X-Forwarded-For should append, not replace."""
    req = _make_request(client=("10.0.0.2", 9999))
    headers = {"host": "example.com", "x-forwarded-for": "10.0.0.1"}
    result = _inject_forwarded_headers(req, headers)
    assert "10.0.0.1" in result["x-forwarded-for"]
    assert "10.0.0.2" in result["x-forwarded-for"]


def test_inject_does_not_mutate_original():
    req = _make_request()
    original = {"host": "example.com"}
    result = _inject_forwarded_headers(req, original)
    assert "x-forwarded-for" not in original
    assert "x-forwarded-for" in result
