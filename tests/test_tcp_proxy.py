"""Tests for TCP/UDP proxy address parsing."""
import pytest

from python_traefik.tcp_proxy import _parse_tcp_addr


def test_parse_tcp_scheme():
    host, port = _parse_tcp_addr("tcp://db-host:3306")
    assert host == "db-host"
    assert port == 3306


def test_parse_http_scheme():
    host, port = _parse_tcp_addr("http://web:8080")
    assert host == "web"
    assert port == 8080


def test_parse_https_scheme():
    host, port = _parse_tcp_addr("https://secure:443")
    assert host == "secure"
    assert port == 443


def test_parse_bare_host_port():
    host, port = _parse_tcp_addr("redis:6379")
    assert host == "redis"
    assert port == 6379


def test_parse_strips_path():
    host, port = _parse_tcp_addr("http://web:8080/path")
    assert host == "web"
    assert port == 8080


def test_parse_no_port_raises():
    with pytest.raises(ValueError, match="no port"):
        _parse_tcp_addr("just-a-host")
