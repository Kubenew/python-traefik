from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class EntryPointConfig:
    name: str
    address: str
    protocol: str = "http"


@dataclass
class RouterConfig:
    name: str
    rule: str
    service: str
    middlewares: List[str] = field(default_factory=list)
    tls: Optional[TLSCertConfig] = None


@dataclass
class ServerConfig:
    url: str


@dataclass
class ServiceConfig:
    name: str
    servers: List[ServerConfig]
    load_balancer: str = "roundrobin"


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
class TLSCertConfig:
    cert_file: str = ""
    key_file: str = ""


@dataclass
class ACMEConfig:
    email: str = ""
    domains: List[str] = field(default_factory=list)
    staging: bool = False
    cert_dir: str = "./certs"


@dataclass
class TLSConfig:
    certificates: List[TLSCertConfig] = field(default_factory=list)
    acme: Optional[ACMEConfig] = None


@dataclass
class HeaderMiddlewareConfig:
    action: str  # set, add, remove
    name: str
    value: str = ""


@dataclass
class RateLimitConfig:
    max_requests: int = 100
    window_seconds: int = 1


@dataclass
class RetryConfig:
    attempts: int = 3


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    recovery_timeout: float = 30.0


@dataclass
class BasicAuthConfig:
    users: Dict[str, str] = field(default_factory=dict)


@dataclass
class RedirectSchemeConfig:
    scheme: str = "https"
    port: int = 443


@dataclass
class MiddlewareConfig:
    name: str
    type: str
    config: dict = field(default_factory=dict)


@dataclass
class ProviderConfig:
    type: str = ""
    address: str = ""
    token: str = ""
    namespace: str = "default"
    poll_interval: int = 30


@dataclass
class AppConfig:
    entrypoints: List[EntryPointConfig]
    routers: List[RouterConfig]
    services: List[ServiceConfig]
    metrics: MetricsConfig
    healthcheck: HealthcheckConfig
    tls: Optional[TLSConfig] = None
    middlewares: List[MiddlewareConfig] = field(default_factory=list)
    providers: List[ProviderConfig] = field(default_factory=list)
    dashboard: bool = False
    dashboard_address: str = ":8080"


def load_config(path: str) -> AppConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    eps = []
    for name, ep in (raw.get("entryPoints") or {}).items():
        eps.append(EntryPointConfig(
            name=name,
            address=ep.get("address", ":8000"),
            protocol=ep.get("protocol", "http"),
        ))

    routers = []
    for name, r in (raw.get("routers") or {}).items():
        tls_cfg = None
        if "tls" in r:
            tls_cfg = TLSCertConfig(
                cert_file=r["tls"].get("certFile", ""),
                key_file=r["tls"].get("keyFile", ""),
            )
        routers.append(RouterConfig(
            name=name,
            rule=r.get("rule", ""),
            service=r.get("service", ""),
            middlewares=r.get("middlewares", []),
            tls=tls_cfg,
        ))

    services = []
    for name, s in (raw.get("services") or {}).items():
        lb = s.get("loadBalancer") or {}
        servers_raw = lb.get("servers") or []
        servers = [ServerConfig(url=sv["url"]) for sv in servers_raw]
        services.append(ServiceConfig(
            name=name,
            servers=servers,
            load_balancer=lb.get("algorithm", "roundrobin"),
        ))

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

    tls_cfg = None
    tls_raw = raw.get("tls")
    if tls_raw:
        certs = []
        for c in tls_raw.get("certificates") or []:
            certs.append(TLSCertConfig(
                cert_file=c.get("certFile", ""),
                key_file=c.get("keyFile", ""),
            ))
        acme_raw = tls_raw.get("acme")
        acme = None
        if acme_raw:
            acme = ACMEConfig(
                email=acme_raw.get("email", ""),
                domains=acme_raw.get("domains", []),
                staging=bool(acme_raw.get("staging", False)),
                cert_dir=str(acme_raw.get("certDir", "./certs")),
            )
        tls_cfg = TLSConfig(certificates=certs, acme=acme)

    middlewares = []
    for name, mw in (raw.get("middlewares") or {}).items():
        if "rateLimit" in mw:
            rl = mw["rateLimit"]
            middlewares.append(MiddlewareConfig(
                name=name, type="rateLimit",
                config={"max_requests": rl.get("maxRequests", 100), "window_seconds": rl.get("windowSeconds", 1)},
            ))
        elif "headers" in mw:
            middlewares.append(MiddlewareConfig(
                name=name, type="headers", config=mw["headers"],
            ))
        elif "retry" in mw:
            middlewares.append(MiddlewareConfig(
                name=name, type="retry", config=mw["retry"],
            ))
        elif "circuitBreaker" in mw:
            cb = mw["circuitBreaker"]
            middlewares.append(MiddlewareConfig(
                name=name, type="circuitBreaker",
                config={"failure_threshold": cb.get("failureThreshold", 5), "recovery_timeout": cb.get("recoveryTimeout", 30.0)},
            ))
        elif "basicAuth" in mw:
            middlewares.append(MiddlewareConfig(
                name=name, type="basicAuth", config={"users": mw["basicAuth"].get("users", {})},
            ))
        elif "redirectScheme" in mw:
            rs = mw["redirectScheme"]
            middlewares.append(MiddlewareConfig(
                name=name, type="redirectScheme",
                config={"scheme": rs.get("scheme", "https"), "port": rs.get("port", 443)},
            ))

    providers_raw = raw.get("providers") or {}
    providers = []
    for ptype, pcfg in providers_raw.items():
        providers.append(ProviderConfig(
            type=ptype,
            address=pcfg.get("address", ""),
            token=pcfg.get("token", ""),
            namespace=pcfg.get("namespace", "default"),
            poll_interval=int(pcfg.get("pollInterval", 30)),
        ))

    dashboard_raw = raw.get("dashboard") or {}
    dashboard_enabled = False
    dashboard_addr = ":8080"
    if isinstance(dashboard_raw, dict):
        dashboard_enabled = bool(dashboard_raw.get("enabled", False))
        dashboard_addr = str(dashboard_raw.get("address", ":8080"))
    elif isinstance(dashboard_raw, bool):
        dashboard_enabled = dashboard_raw

    return AppConfig(
        entrypoints=eps,
        routers=routers,
        services=services,
        metrics=metrics,
        healthcheck=healthcheck,
        tls=tls_cfg,
        middlewares=middlewares,
        providers=providers,
        dashboard=dashboard_enabled,
        dashboard_address=dashboard_addr,
    )
