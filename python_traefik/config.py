from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import yaml


@dataclass
class EntryPointConfig:
    name: str
    address: str  # e.g. ":8000" or "0.0.0.0:8000"


@dataclass
class RouterConfig:
    name: str
    rule: str
    service: str


@dataclass
class ServerConfig:
    url: str


@dataclass
class ServiceConfig:
    name: str
    servers: List[ServerConfig]


@dataclass
class MetricsConfig:
    enabled: bool = False
    path: str = "/metrics"


@dataclass
class HealthcheckConfig:
    enabled: bool = False
    interval_seconds: int = 5
    timeout_seconds: int = 2
    path: str = "/health"


@dataclass
class AppConfig:
    entrypoints: List[EntryPointConfig]
    routers: List[RouterConfig]
    services: List[ServiceConfig]
    metrics: MetricsConfig
    healthcheck: HealthcheckConfig


def load_config(path: str) -> AppConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    eps = []
    for name, ep in (raw.get("entryPoints") or {}).items():
        eps.append(EntryPointConfig(name=name, address=ep["address"]))

    routers = []
    for name, r in (raw.get("routers") or {}).items():
        routers.append(RouterConfig(name=name, rule=r["rule"], service=r["service"]))

    services = []
    for name, s in (raw.get("services") or {}).items():
        lb = s.get("loadBalancer") or {}
        servers_raw = lb.get("servers") or []
        servers = [ServerConfig(url=sv["url"]) for sv in servers_raw]
        services.append(ServiceConfig(name=name, servers=servers))

    metrics_raw = raw.get("metrics") or {}
    metrics = MetricsConfig(
        enabled=bool(metrics_raw.get("enabled", False)),
        path=str(metrics_raw.get("path", "/metrics")),
    )

    hc_raw = raw.get("healthcheck") or {}
    healthcheck = HealthcheckConfig(
        enabled=bool(hc_raw.get("enabled", False)),
        interval_seconds=int(hc_raw.get("interval_seconds", 5)),
        timeout_seconds=int(hc_raw.get("timeout_seconds", 2)),
        path=str(hc_raw.get("path", "/health")),
    )

    return AppConfig(
        entrypoints=eps,
        routers=routers,
        services=services,
        metrics=metrics,
        healthcheck=healthcheck,
    )
