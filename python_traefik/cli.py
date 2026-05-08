from __future__ import annotations

import asyncio
import typer
import uvicorn

from .config import load_config
from .router import RouterTable
from .registry import ServiceRegistry
from .app import create_app
from .healthcheck import healthcheck_loop

app = typer.Typer(help="python-traefik - minimal Traefik-like reverse proxy")


@app.command()
def run(config: str = typer.Option(..., "--config", "-c", help="Path to YAML config file")):
    cfg = load_config(config)

    router_table = RouterTable()
    for r in cfg.routers:
        router_table.add_router(r.name, r.rule, r.service)

    registry = ServiceRegistry()
    for s in cfg.services:
        registry.register_service(s.name, [sv.url for sv in s.servers])

    if not cfg.entrypoints:
        raise typer.BadParameter("No entryPoints configured.")

    # MVP: only first entrypoint
    ep = cfg.entrypoints[0]
    host, port = "0.0.0.0", 8000
    addr = ep.address.strip()
    if addr.startswith(":"):
        port = int(addr[1:])
    else:
        if ":" in addr:
            host, port_str = addr.split(":", 1)
            port = int(port_str)
        else:
            raise typer.BadParameter(f"Invalid entrypoint address: {addr}")

    starlette_app = create_app(
        router_table=router_table,
        registry=registry,
        metrics_enabled=cfg.metrics.enabled,
        metrics_path=cfg.metrics.path,
    )

    loop = asyncio.get_event_loop()
    if cfg.healthcheck.enabled:
        loop.create_task(
            healthcheck_loop(
                registry=registry,
                interval_seconds=cfg.healthcheck.interval_seconds,
                timeout_seconds=cfg.healthcheck.timeout_seconds,
                path=cfg.healthcheck.path,
            )
        )

    uvicorn.run(starlette_app, host=host, port=port)


if __name__ == "__main__":
    app()
