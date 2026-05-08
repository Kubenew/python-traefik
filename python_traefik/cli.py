from __future__ import annotations

import asyncio
import logging
import os
import ssl
import sys
from typing import Optional

import typer
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Route, Mount

from .app import create_app
from .config import AppConfig, MiddlewareConfig, load_config
from .dashboard import DashboardState, create_dashboard_app
from .discovery import (
    ConsulProvider,
    DiscoveryManager,
    KubernetesProvider,
    ProviderConfig as DiscProviderConfig,
)
from .healthcheck import healthcheck_loop
from .metrics import metrics_response
from .middleware import (
    BasicAuthMiddleware,
    CircuitBreakerMiddleware,
    HeaderAction,
    HeadersMiddleware,
    Middleware,
    MiddlewarePipeline,
    RateLimiterMiddleware,
    RedirectSchemeMiddleware,
    RetryMiddleware,
)
from .registry import ServiceRegistry
from .router import RouterTable
from .tcp_proxy import TCPProxy, UDPProxy
from .tls import (
    ACMEConfig as TLSACMEConfig,
    CertificateStore,
    TLSConfig,
    acme_provision,
    load_cert_chain,
    make_ssl_context,
)

logger = logging.getLogger("python_traefik")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

app = typer.Typer(help="python-traefik - Traefik-like reverse proxy in Python")


def _build_middleware_pipeline(cfg: AppConfig) -> dict[str, MiddlewarePipeline]:
    pipelines: dict[str, MiddlewarePipeline] = {}
    for mw_cfg in cfg.middlewares:
        mw = _create_middleware(mw_cfg)
        if mw:
            if mw_cfg.name not in pipelines:
                pipelines[mw_cfg.name] = MiddlewarePipeline()
            pipelines[mw_cfg.name].add(mw)
    return pipelines


def _create_middleware(mw_cfg: MiddlewareConfig) -> Optional[Middleware]:
    t = mw_cfg.type
    c = mw_cfg.config
    if t == "rateLimit":
        return RateLimiterMiddleware(
            max_requests=int(c.get("max_requests", 100)),
            window_seconds=int(c.get("window_seconds", 1)),
        )
    elif t == "headers":
        actions = []
        for op in ("set", "add", "remove"):
            for k, v in c.get(op, {}).items():
                actions.append(HeaderAction(action=op, name=k, value=str(v)))
        return HeadersMiddleware(actions) if actions else None
    elif t == "retry":
        return RetryMiddleware(attempts=int(c.get("attempts", 3)))
    elif t == "circuitBreaker":
        return CircuitBreakerMiddleware(
            failure_threshold=int(c.get("failure_threshold", 5)),
            recovery_timeout=float(c.get("recovery_timeout", 30.0)),
        )
    elif t == "basicAuth":
        return BasicAuthMiddleware(users=c.get("users", {}))
    elif t == "redirectScheme":
        return RedirectSchemeMiddleware(
            scheme=c.get("scheme", "https"),
            port=int(c.get("port", 443)),
        )
    return None


def _parse_addr(addr: str) -> tuple[str, int]:
    host, port_str = "0.0.0.0", "8000"
    addr = addr.strip()
    if addr.startswith(":"):
        port_str = addr[1:]
    elif ":" in addr:
        host, port_str = addr.split(":", 1)
    else:
        host = addr
    return host, int(port_str)


async def _run_async(cfg: AppConfig):
    registry = ServiceRegistry()
    router_table = RouterTable()
    cert_store = CertificateStore()
    middleware_pipelines = _build_middleware_pipeline(cfg)
    tls_configs: dict[str, ssl.SSLContext] = {}

    for r in cfg.routers:
        router_table.add_router(r.name, r.rule, r.service)

    for s in cfg.services:
        registry.register_service(s.name, [sv.url for sv in s.servers])

    if cfg.tls:
        for cert_cfg in cfg.tls.certificates:
            if cert_cfg.cert_file and cert_cfg.key_file:
                cert_pem, key_pem = load_cert_chain(cert_cfg.cert_file, cert_cfg.key_file)
                ctx = make_ssl_context(cert_pem, key_pem)
                tls_configs["default"] = ctx
        if cfg.tls.acme:
            acme_cfg = TLSACMEConfig(
                email=cfg.tls.acme.email,
                domains=cfg.tls.acme.domains,
                staging=cfg.tls.acme.staging,
                cert_dir=cfg.tls.acme.cert_dir,
            )
            certs = await acme_provision(acme_cfg, cert_store)
            for c in certs:
                ctx = make_ssl_context(c.cert_pem.encode(), c.key_pem.encode())
                tls_configs[c.domain] = ctx

    http_eps = [ep for ep in cfg.entrypoints if ep.protocol == "http" or ep.protocol == "https"]
    tcp_eps = [ep for ep in cfg.entrypoints if ep.protocol == "tcp"]
    udp_eps = [ep for ep in cfg.entrypoints if ep.protocol == "udp"]

    proxy_tasks = []

    for ep in http_eps:
        host, port = _parse_addr(ep.address)
        starlette_app = create_app(
            router_table=router_table,
            registry=registry,
            metrics_enabled=cfg.metrics.enabled,
            metrics_path=cfg.metrics.path,
        )

        pipelined_handler = starlette_app
        if middleware_pipelines:
            for router_cfg in cfg.routers:
                pipeline = MiddlewarePipeline()
                for mw_name in router_cfg.middlewares:
                    if mw_name in middleware_pipelines:
                        for mw in middleware_pipelines[mw_name]._middlewares:
                            pipeline.add(mw)
                if pipeline._middlewares:
                    routes = starlette_app.routes
                    chain = pipeline.build_chain(lambda req: None)

            starlette_app = create_app(
                router_table=router_table,
                registry=registry,
                metrics_enabled=cfg.metrics.enabled,
                metrics_path=cfg.metrics.path,
            )

        ssl_ctx = None
        if ep.protocol == "https":
            ssl_ctx = tls_configs.get("default")

        config = uvicorn.Config(
            app=starlette_app,
            host=host,
            port=port,
            ssl_certfile=None,
            ssl_keyfile=None,
            log_level="info",
        )
        if ssl_ctx:
            config.ssl_certfile = None
            config.ssl_keyfile = None

        server = uvicorn.Server(config=config)
        proxy_tasks.append(asyncio.create_task(server.serve()))

    for ep in tcp_eps:
        host, port = _parse_addr(ep.address)
        svc_name = f"tcp-{ep.name}"
        if svc_name not in registry.services:
            logger.warning("No service for TCP entrypoint %s, skipping", ep.name)
            continue
        tls_ctx = tls_configs.get("default") if ep.protocol == "tcp" else None
        tcp_proxy = TCPProxy(
            host=host,
            port=port,
            registry=registry,
            service_name=svc_name,
            tls_context=tls_ctx,
        )
        proxy_tasks.append(asyncio.create_task(tcp_proxy.start()))

    for ep in udp_eps:
        host, port = _parse_addr(ep.address)
        svc_name = f"udp-{ep.name}"
        udp_proxy = UDPProxy(
            host=host,
            port=port,
            registry=registry,
            service_name=svc_name,
        )
        proxy_tasks.append(asyncio.create_task(udp_proxy.start()))

    if cfg.healthcheck.enabled:
        asyncio.create_task(
            healthcheck_loop(
                registry=registry,
                interval_seconds=cfg.healthcheck.interval_seconds,
                timeout_seconds=cfg.healthcheck.timeout_seconds,
                path=cfg.healthcheck.path,
            )
        )

    discovery_mgr = DiscoveryManager(registry=registry)
    for p in cfg.providers:
        disc_cfg = DiscProviderConfig(
            type=p.type,
            address=p.address,
            token=p.token,
            namespace=p.namespace,
            poll_interval=p.poll_interval,
        )
        if p.type == "consul":
            discovery_mgr.add_provider(ConsulProvider(disc_cfg))
        elif p.type == "kubernetes":
            discovery_mgr.add_provider(KubernetesProvider(disc_cfg))
    if discovery_mgr._providers:
        await discovery_mgr.start()

    dashboard_state = DashboardState(
        router_table=router_table,
        registry=registry,
        cert_store=cert_store,
        providers=[p.type for p in cfg.providers] if cfg.providers else ["file"],
        http_entrypoints=len(http_eps),
        tcp_entrypoints=len(tcp_eps),
    )

    if cfg.dashboard:
        host, port = _parse_addr(cfg.dashboard_address)
        dash_app = create_dashboard_app(dashboard_state)
        dash_config = uvicorn.Config(app=dash_app, host=host, port=port, log_level="info")
        dash_server = uvicorn.Server(config=dash_config)
        proxy_tasks.append(asyncio.create_task(dash_server.serve()))

    if proxy_tasks:
        await asyncio.gather(*proxy_tasks)

    if discovery_mgr._providers:
        await discovery_mgr.stop()


@app.command()
def run(
    config: str = typer.Option(..., "--config", "-c", help="Path to YAML config file"),
):
    cfg = load_config(config)
    if not cfg.entrypoints:
        raise typer.BadParameter("No entryPoints configured.")
    asyncio.run(_run_async(cfg))


if __name__ == "__main__":
    app()
