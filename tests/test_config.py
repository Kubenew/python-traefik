"""Tests for config loading and validation."""
import os
import tempfile

import pytest

from python_traefik.config import load_config


MINIMAL_CONFIG = """\
entryPoints:
  web:
    address: ":8000"

routers:
  test:
    rule: "Host(`test.com`)"
    service: "test_svc"

services:
  test_svc:
    loadBalancer:
      servers:
        - url: "http://localhost:9000"
"""

FULL_CONFIG = """\
entryPoints:
  web:
    address: ":8000"

tcpEntryPoints:
  mysql:
    address: ":3306"
    service: "db_svc"
    tls: true

udpEntryPoints:
  dns:
    address: ":5353"
    service: "dns_svc"

routers:
  app:
    rule: "Host(`example.com`)"
    service: "app_svc"
    middlewares:
      - "rl"
    priority: 50
    entryPoints:
      - "web"

services:
  app_svc:
    loadBalancer:
      servers:
        - url: "http://localhost:5000"
  db_svc:
    loadBalancer:
      servers:
        - url: "tcp://db:3306"
  dns_svc:
    loadBalancer:
      servers:
        - url: "tcp://dns:53"

middlewares:
  rl:
    type: "rate-limit"
    maxRequests: 50

tls:
  enabled: true
  minVersion: "TLSv1.3"
  acme:
    email: "admin@example.com"
    domains:
      - "example.com"
    staging: true

dashboard:
  enabled: true
  address: ":9090"

providers:
  consul:
    type: "consul"
    address: "consul:8500"
    pollInterval: 10

metrics:
  enabled: true
  path: "/prom"

healthcheck:
  enabled: true
  interval_seconds: 10
  timeout_seconds: 3
  path: "/healthz"

logging:
  level: "DEBUG"
  accessLog: false
"""


def _write_config(content: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".yml")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


def test_minimal_config():
    path = _write_config(MINIMAL_CONFIG)
    try:
        cfg = load_config(path)
        assert len(cfg.entrypoints) == 1
        assert cfg.entrypoints[0].address == ":8000"
        assert len(cfg.routers) == 1
        assert cfg.routers[0].name == "test"
        assert len(cfg.services) == 1
        assert cfg.metrics.enabled is False
        assert cfg.healthcheck.enabled is False
        assert cfg.dashboard.enabled is False
        assert cfg.tls.enabled is False
        assert len(cfg.middlewares) == 0
        assert len(cfg.providers) == 0
    finally:
        os.unlink(path)


def test_full_config():
    path = _write_config(FULL_CONFIG)
    try:
        cfg = load_config(path)
        # Entrypoints
        assert len(cfg.entrypoints) == 1
        assert len(cfg.tcp_entrypoints) == 1
        assert cfg.tcp_entrypoints[0].tls is True
        assert len(cfg.udp_entrypoints) == 1

        # Routers
        assert len(cfg.routers) == 1
        assert cfg.routers[0].middlewares == ["rl"]
        assert cfg.routers[0].priority == 50

        # Middlewares
        assert len(cfg.middlewares) == 1
        assert cfg.middlewares[0].type == "rate-limit"
        assert cfg.middlewares[0].options["maxRequests"] == 50

        # TLS
        assert cfg.tls.enabled is True
        assert cfg.tls.min_version == "TLSv1.3"
        assert cfg.tls.acme is not None
        assert cfg.tls.acme.email == "admin@example.com"

        # Dashboard
        assert cfg.dashboard.enabled is True
        assert cfg.dashboard.address == ":9090"

        # Providers
        assert len(cfg.providers) == 1
        assert cfg.providers[0].type == "consul"
        assert cfg.providers[0].poll_interval == 10

        # Metrics
        assert cfg.metrics.enabled is True
        assert cfg.metrics.path == "/prom"

        # Healthcheck
        assert cfg.healthcheck.interval_seconds == 10
        assert cfg.healthcheck.path == "/healthz"

        # Logging
        assert cfg.logging.level == "DEBUG"
        assert cfg.logging.access_log is False
    finally:
        os.unlink(path)


def test_empty_config():
    path = _write_config("")
    try:
        cfg = load_config(path)
        assert len(cfg.entrypoints) == 0
        assert len(cfg.routers) == 0
        assert len(cfg.services) == 0
    finally:
        os.unlink(path)


def test_router_priority_ordering():
    """Routers should be sorted by priority descending."""
    content = """\
entryPoints:
  web:
    address: ":8000"
routers:
  low:
    rule: "Host(`low.com`)"
    service: "s"
    priority: 1
  high:
    rule: "Host(`high.com`)"
    service: "s"
    priority: 100
  mid:
    rule: "Host(`mid.com`)"
    service: "s"
    priority: 50
services:
  s:
    loadBalancer:
      servers:
        - url: "http://localhost:9000"
"""
    path = _write_config(content)
    try:
        cfg = load_config(path)
        priorities = [r.priority for r in cfg.routers]
        assert priorities == sorted(priorities, reverse=True)
    finally:
        os.unlink(path)
