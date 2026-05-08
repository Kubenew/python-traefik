from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import yaml


# ---------------------------------------------------------------------------
# Entrypoints
# ---------------------------------------------------------------------------

@dataclass
class EntryPointConfig:
    name: str
    address: str  # e.g. ":8000" or "0.0.0.0:8000"


@dataclass
class TCPEntryPointConfig:
    name: str
    address: str
    service: str
    tls: bool = False


@dataclass
class UDPEntryPointConfig:
    name: str
    address: str
    service: str


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

@dataclass
class RouterConfig:
    name: str
    rule: str
    service: str
    middlewares: List[str] = field(default_factory=list)
    priority: int = 0
    entrypoints: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------

@dataclass
class ServerConfig:
    url: str


@dataclass
class ServiceConfig:
    name: str
    servers: List[ServerConfig]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@dataclass
class MetricsConfig:
    enabled: bool = False
    path: str = "/metrics"


# ---------------------------------------------------------------------------
# Healthcheck
# ---------------------------------------------------------------------------

@dataclass
class HealthcheckConfig:
    enabled: bool = False
    interval_seconds: int = 5
    timeout_seconds: int = 2
    path: str = "/health"


# ---------------------------------------------------------------------------
# TLS / ACME
# ---------------------------------------------------------------------------

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
    challenge_type: str = "tls-alpn-01"


@dataclass
class TLSConfig:
    enabled: bool = False
    certificates: List[TLSCertConfig] = field(default_factory=list)
    acme: Optional[ACMEConfig] = None
    min_version: str = "TLSv1.2"


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

@dataclass
class MiddlewareConfig:
    name: str
    type: str  # rate-limit, headers, retry, circuit-breaker, basic-auth, redirect-scheme
    options: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@dataclass
class DashboardConfig:
    enabled: bool = False
    address: str = ":8080"


# ---------------------------------------------------------------------------
# Service Discovery Providers
# ---------------------------------------------------------------------------

@dataclass
class ProviderConfig:
    type: str  # consul, kubernetes
    address: str = ""
    token: str = ""
    scheme: str = "http"
    namespace: str = "default"
    labels: Dict[str, str] = field(default_factory=dict)
    poll_interval: int = 30


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

@dataclass
class LoggingConfig:
    level: str = "INFO"
    access_log: bool = True


# ---------------------------------------------------------------------------
# Top-level Config
# ---------------------------------------------------------------------------

@dataclass
class AppConfig:
    entrypoints: List[EntryPointConfig]
    routers: List[RouterConfig]
    services: List[ServiceConfig]
    metrics: MetricsConfig
    healthcheck: HealthcheckConfig
    tls: TLSConfig = field(default_factory=TLSConfig)
    middlewares: List[MiddlewareConfig] = field(default_factory=list)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    providers: List[ProviderConfig] = field(default_factory=list)
    tcp_entrypoints: List[TCPEntryPointConfig] = field(default_factory=list)
    udp_entrypoints: List[UDPEntryPointConfig] = field(default_factory=list)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_config(path: str) -> AppConfig:
    """Parse a YAML config file into an AppConfig."""
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    # --- Entrypoints (HTTP) ---
    eps = []
    for name, ep in (raw.get("entryPoints") or {}).items():
        if isinstance(ep, dict) and "address" in ep:
            eps.append(EntryPointConfig(name=name, address=ep["address"]))

    # --- TCP Entrypoints ---
    tcp_eps = []
    for name, ep in (raw.get("tcpEntryPoints") or {}).items():
        tcp_eps.append(TCPEntryPointConfig(
            name=name,
            address=ep["address"],
            service=ep.get("service", ""),
            tls=bool(ep.get("tls", False)),
        ))

    # --- UDP Entrypoints ---
    udp_eps = []
    for name, ep in (raw.get("udpEntryPoints") or {}).items():
        udp_eps.append(UDPEntryPointConfig(
            name=name,
            address=ep["address"],
            service=ep.get("service", ""),
        ))

    # --- Routers ---
    routers = []
    for name, r in (raw.get("routers") or {}).items():
        routers.append(RouterConfig(
            name=name,
            rule=r["rule"],
            service=r["service"],
            middlewares=r.get("middlewares", []),
            priority=int(r.get("priority", 0)),
            entrypoints=r.get("entryPoints", []),
        ))
    # Sort by priority descending so higher-priority routers match first
    routers.sort(key=lambda r: r.priority, reverse=True)

    # --- Services ---
    services = []
    for name, s in (raw.get("services") or {}).items():
        lb = s.get("loadBalancer") or {}
        servers_raw = lb.get("servers") or []
        servers = [ServerConfig(url=sv["url"]) for sv in servers_raw]
        services.append(ServiceConfig(name=name, servers=servers))

    # --- Metrics ---
    metrics_raw = raw.get("metrics") or {}
    metrics = MetricsConfig(
        enabled=bool(metrics_raw.get("enabled", False)),
        path=str(metrics_raw.get("path", "/metrics")),
    )

    # --- Healthcheck ---
    hc_raw = raw.get("healthcheck") or {}
    healthcheck = HealthcheckConfig(
        enabled=bool(hc_raw.get("enabled", False)),
        interval_seconds=int(hc_raw.get("interval_seconds", 5)),
        timeout_seconds=int(hc_raw.get("timeout_seconds", 2)),
        path=str(hc_raw.get("path", "/health")),
    )

    # --- TLS ---
    tls_raw = raw.get("tls") or {}
    tls_certs = []
    for c in tls_raw.get("certificates") or []:
        tls_certs.append(TLSCertConfig(
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
            cert_dir=acme_raw.get("certDir", "./certs"),
            challenge_type=acme_raw.get("challengeType", "tls-alpn-01"),
        )
    tls = TLSConfig(
        enabled=bool(tls_raw.get("enabled", False)),
        certificates=tls_certs,
        acme=acme,
        min_version=tls_raw.get("minVersion", "TLSv1.2"),
    )

    # --- Middlewares ---
    middlewares = []
    for name, mw_raw in (raw.get("middlewares") or {}).items():
        mw_type = mw_raw.get("type", "")
        options = {k: v for k, v in mw_raw.items() if k != "type"}
        middlewares.append(MiddlewareConfig(name=name, type=mw_type, options=options))

    # --- Dashboard ---
    dash_raw = raw.get("dashboard") or {}
    dashboard = DashboardConfig(
        enabled=bool(dash_raw.get("enabled", False)),
        address=str(dash_raw.get("address", ":8080")),
    )

    # --- Providers ---
    providers = []
    for name, p in (raw.get("providers") or {}).items():
        providers.append(ProviderConfig(
            type=p.get("type", name),
            address=p.get("address", ""),
            token=p.get("token", ""),
            scheme=p.get("scheme", "http"),
            namespace=p.get("namespace", "default"),
            labels=p.get("labels", {}),
            poll_interval=int(p.get("pollInterval", 30)),
        ))

    # --- Logging ---
    log_raw = raw.get("logging") or {}
    log_cfg = LoggingConfig(
        level=log_raw.get("level", "INFO").upper(),
        access_log=bool(log_raw.get("accessLog", True)),
    )

    return AppConfig(
        entrypoints=eps,
        routers=routers,
        services=services,
        metrics=metrics,
        healthcheck=healthcheck,
        tls=tls,
        middlewares=middlewares,
        dashboard=dashboard,
        providers=providers,
        tcp_entrypoints=tcp_eps,
        udp_entrypoints=udp_eps,
        logging=log_cfg,
    )
