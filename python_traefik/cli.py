from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Optional

import typer
import uvicorn

from .config import load_config, AppConfig, MiddlewareConfig
from .router import RouterTable
from .registry import ServiceRegistry
from .app import create_app
from .healthcheck import healthcheck_loop
from .middleware import (
    Middleware,
    RateLimiterMiddleware,
    HeadersMiddleware,
    HeaderAction,
    RetryMiddleware,
    CircuitBreakerMiddleware,
    BasicAuthMiddleware,
    RedirectSchemeMiddleware,
)
from .tcp_proxy import TCPProxy, UDPProxy
from .tls import CertificateStore, TLSConfig as TLSCfg, ACMEConfig as ACMECfg, acme_provision, load_cert_chain, make_ssl_context
from .dashboard import DashboardState, create_dashboard_app
from .discovery import DiscoveryManager, ConsulProvider, KubernetesProvider, ProviderConfig as DiscProviderConfig

from . import __version__

app = typer.Typer(help="python-traefik — a Traefik-like reverse proxy in Python")

logger = logging.getLogger("python_traefik")


def _parse_address(addr: str) -> tuple[str, int]:
    """Parse ':8000' or '0.0.0.0:8000' into (host, port)."""
    addr = addr.strip()
    if addr.startswith(":"):
        return "0.0.0.0", int(addr[1:])
    if ":" in addr:
        host, port_str = addr.rsplit(":", 1)
        return host, int(port_str)
    raise typer.BadParameter(f"Invalid address: {addr}")


def _build_middleware(cfg: MiddlewareConfig) -> Optional[Middleware]:
    """Instantiate a Middleware from its config."""
    t = cfg.type
    opts = cfg.options

    if t == "rate-limit":
        return RateLimiterMiddleware(
            max_requests=int(opts.get("maxRequests", 100)),
            window_seconds=int(opts.get("windowSeconds", 1)),
        )
    elif t == "headers":
        actions = []
        for a in opts.get("actions", []):
            actions.append(HeaderAction(
                action=a.get("action", "set"),
                name=a.get("name", ""),
                value=a.get("value", ""),
            ))
        return HeadersMiddleware(actions=actions)
    elif t == "retry":
        return RetryMiddleware(attempts=int(opts.get("attempts", 3)))
    elif t == "circuit-breaker":
        return CircuitBreakerMiddleware(
            failure_threshold=int(opts.get("failureThreshold", 5)),
            recovery_timeout=float(opts.get("recoveryTimeout", 30.0)),
        )
    elif t == "basic-auth":
        users = opts.get("users", {})
        return BasicAuthMiddleware(users=users)
    elif t == "redirect-scheme":
        return RedirectSchemeMiddleware(
            scheme=opts.get("scheme", "https"),
            port=int(opts.get("port", 443)),
        )
    else:
        logger.warning("Unknown middleware type: %s", t)
        return None


@app.command()
def run(
    config: str = typer.Option(..., "--config", "-c", help="Path to YAML config file"),
    log_level: str = typer.Option("", "--log-level", "-l", help="Override log level (DEBUG, INFO, WARNING, ERROR)"),
):
    """Start the python-traefik reverse proxy."""
    cfg = load_config(config)

    # --- Logging ---
    level = log_level.upper() if log_level else cfg.logging.level
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info("python-traefik v%s starting", __version__)

    # --- Router Table ---
    router_table = RouterTable()
    for r in cfg.routers:
        router_table.add_router(
            r.name, r.rule, r.service,
            middlewares=r.middlewares,
            priority=r.priority,
            entrypoints=r.entrypoints,
        )
    logger.info("Loaded %d routers", len(cfg.routers))

    # --- Service Registry ---
    registry = ServiceRegistry()
    for s in cfg.services:
        registry.register_service(s.name, [sv.url for sv in s.servers])
    logger.info("Registered %d services", len(cfg.services))

    # --- Middlewares ---
    middleware_map: dict[str, Middleware] = {}
    for mw_cfg in cfg.middlewares:
        mw = _build_middleware(mw_cfg)
        if mw:
            middleware_map[mw_cfg.name] = mw
            logger.info("Loaded middleware: %s (%s)", mw_cfg.name, mw_cfg.type)

    # --- TLS / Certs ---
    cert_store = CertificateStore()

    # --- Entrypoint validation ---
    if not cfg.entrypoints and not cfg.tcp_entrypoints and not cfg.udp_entrypoints:
        raise typer.BadParameter("No entryPoints configured.")

    # --- HTTP entrypoint ---
    if not cfg.entrypoints:
        raise typer.BadParameter("At least one HTTP entryPoint is required.")

    ep = cfg.entrypoints[0]
    host, port = _parse_address(ep.address)

    # --- Build main ASGI app ---
    starlette_app = create_app(
        router_table=router_table,
        registry=registry,
        metrics_enabled=cfg.metrics.enabled,
        metrics_path=cfg.metrics.path,
        middleware_map=middleware_map,
        access_log=cfg.logging.access_log,
    )

    # Run the async startup inside uvicorn's event loop via lifespan-like approach
    # We use uvicorn.Config + Server for more control
    uvi_config = uvicorn.Config(
        app=starlette_app,
        host=host,
        port=port,
        log_level=level.lower(),
        access_log=False,  # We handle our own access log
    )
    server = uvicorn.Server(uvi_config)

    async def _main():
        """Async main — starts all subsystems, then the HTTP server."""

        # --- TLS provisioning ---
        if cfg.tls.enabled:
            for cert_cfg in cfg.tls.certificates:
                if cert_cfg.cert_file and cert_cfg.key_file:
                    from .tls import load_cert_chain, Certificate
                    cert_pem, key_pem = load_cert_chain(cert_cfg.cert_file, cert_cfg.key_file)
                    cert = Certificate(cert_pem=cert_pem.decode(), key_pem=key_pem.decode(), domain="manual")
                    cert_store.add(cert)
                    logger.info("Loaded TLS cert from %s", cert_cfg.cert_file)
            if cfg.tls.acme:
                acme_cfg = ACMECfg(
                    email=cfg.tls.acme.email,
                    domains=cfg.tls.acme.domains,
                    staging=cfg.tls.acme.staging,
                    cert_dir=cfg.tls.acme.cert_dir,
                    challenge_type=cfg.tls.acme.challenge_type,
                )
                await acme_provision(acme_cfg, cert_store)
                logger.info("ACME provisioning complete")

        # --- Health checks ---
        if cfg.healthcheck.enabled:
            asyncio.create_task(
                healthcheck_loop(
                    registry=registry,
                    interval_seconds=cfg.healthcheck.interval_seconds,
                    timeout_seconds=cfg.healthcheck.timeout_seconds,
                    path=cfg.healthcheck.path,
                )
            )
            logger.info("Health checks enabled (interval=%ds)", cfg.healthcheck.interval_seconds)

        # --- TCP Proxies ---
        tcp_proxies: list[TCPProxy] = []
        for tcp_ep in cfg.tcp_entrypoints:
            tcp_host, tcp_port = _parse_address(tcp_ep.address)
            ssl_ctx = None
            if tcp_ep.tls and cert_store.list():
                cert = cert_store.list()[0]
                ssl_ctx = make_ssl_context(cert.cert_pem.encode(), cert.key_pem.encode())
            proxy = TCPProxy(
                host=tcp_host, port=tcp_port,
                registry=registry, service_name=tcp_ep.service,
                tls_context=ssl_ctx,
            )
            await proxy.start()
            tcp_proxies.append(proxy)

        # --- UDP Proxies ---
        udp_proxies: list[UDPProxy] = []
        for udp_ep in cfg.udp_entrypoints:
            udp_host, udp_port = _parse_address(udp_ep.address)
            proxy = UDPProxy(
                host=udp_host, port=udp_port,
                registry=registry, service_name=udp_ep.service,
            )
            await proxy.start()
            udp_proxies.append(proxy)

        # --- Service Discovery ---
        discovery_mgr: Optional[DiscoveryManager] = None
        provider_names: list[str] = []
        if cfg.providers:
            discovery_mgr = DiscoveryManager(registry)
            for p_cfg in cfg.providers:
                prov_config = DiscProviderConfig(
                    type=p_cfg.type,
                    address=p_cfg.address,
                    token=p_cfg.token,
                    scheme=p_cfg.scheme,
                    namespace=p_cfg.namespace,
                    labels=p_cfg.labels,
                    poll_interval=p_cfg.poll_interval,
                )
                if p_cfg.type == "consul":
                    discovery_mgr.add_provider(ConsulProvider(prov_config))
                    provider_names.append("consul")
                elif p_cfg.type == "kubernetes":
                    discovery_mgr.add_provider(KubernetesProvider(prov_config))
                    provider_names.append("kubernetes")
                else:
                    logger.warning("Unknown provider type: %s", p_cfg.type)
            await discovery_mgr.start()

        # --- Dashboard ---
        dashboard_server = None
        if cfg.dashboard.enabled:
            dash_state = DashboardState(
                router_table=router_table,
                registry=registry,
                cert_store=cert_store,
                providers=provider_names or ["file"],
                http_entrypoints=len(cfg.entrypoints),
                tcp_entrypoints=len(cfg.tcp_entrypoints),
            )
            dash_app = create_dashboard_app(dash_state)
            dash_host, dash_port = _parse_address(cfg.dashboard.address)
            dash_config = uvicorn.Config(
                app=dash_app,
                host=dash_host,
                port=dash_port,
                log_level="warning",
                access_log=False,
            )
            dashboard_server = uvicorn.Server(dash_config)
            asyncio.create_task(dashboard_server.serve())
            logger.info("Dashboard available at http://%s:%d/dashboard", dash_host, dash_port)

        # --- Start main HTTP server ---
        logger.info("HTTP proxy listening on %s:%d", host, port)
        await server.serve()

        # --- Cleanup ---
        for proxy in tcp_proxies:
            await proxy.stop()
        for proxy in udp_proxies:
            await proxy.stop()
        if discovery_mgr:
            await discovery_mgr.stop()

    asyncio.run(_main())


@app.command()
def version():
    """Print the version and exit."""
    typer.echo(f"python-traefik v{__version__}")


@app.command()
def validate(
    config: str = typer.Option(..., "--config", "-c", help="Path to YAML config file"),
):
    """Validate a config file without starting the proxy."""
    try:
        cfg = load_config(config)
        typer.echo(f"[OK] Config valid: {len(cfg.entrypoints)} HTTP entrypoints, "
                    f"{len(cfg.routers)} routers, {len(cfg.services)} services, "
                    f"{len(cfg.middlewares)} middlewares, "
                    f"{len(cfg.tcp_entrypoints)} TCP entrypoints, "
                    f"{len(cfg.udp_entrypoints)} UDP entrypoints")
        if cfg.tls.enabled:
            typer.echo(f"  TLS: {len(cfg.tls.certificates)} certs, ACME={'yes' if cfg.tls.acme else 'no'}")
        if cfg.dashboard.enabled:
            typer.echo(f"  Dashboard: {cfg.dashboard.address}")
        if cfg.providers:
            typer.echo(f"  Providers: {', '.join(p.type for p in cfg.providers)}")
    except Exception as e:
        typer.echo(f"[ERR] Config error: {e}", err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
