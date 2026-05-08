"""Tests for the RoundRobinBalancer."""
import pytest

from python_traefik.balancer import Backend, RoundRobinBalancer


def test_round_robin_cycles():
    backends = [Backend(url="http://a"), Backend(url="http://b"), Backend(url="http://c")]
    lb = RoundRobinBalancer(backends)
    urls = [lb.next_backend().url for _ in range(6)]
    assert urls == ["http://a", "http://b", "http://c", "http://a", "http://b", "http://c"]


def test_skips_unhealthy():
    backends = [Backend(url="http://a"), Backend(url="http://b", healthy=False), Backend(url="http://c")]
    lb = RoundRobinBalancer(backends)
    urls = [lb.next_backend().url for _ in range(4)]
    assert "http://b" not in urls


def test_all_unhealthy_returns_none():
    backends = [Backend(url="http://a", healthy=False), Backend(url="http://b", healthy=False)]
    lb = RoundRobinBalancer(backends)
    assert lb.next_backend() is None


def test_single_backend():
    backends = [Backend(url="http://only")]
    lb = RoundRobinBalancer(backends)
    assert lb.next_backend().url == "http://only"
    assert lb.next_backend().url == "http://only"


def test_empty_raises():
    with pytest.raises(ValueError, match="at least one backend"):
        RoundRobinBalancer([])


def test_backend_goes_unhealthy_then_healthy():
    backends = [Backend(url="http://a"), Backend(url="http://b")]
    lb = RoundRobinBalancer(backends)
    assert lb.next_backend().url == "http://a"
    backends[1].healthy = False
    # Next calls should skip b
    assert lb.next_backend().url == "http://a"
    assert lb.next_backend().url == "http://a"
    # Bring b back
    backends[1].healthy = True
    urls = [lb.next_backend().url for _ in range(4)]
    assert "http://b" in urls
