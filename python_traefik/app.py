from __future__ import annotations

import logging
import time
from typing import Optional

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route, Mount

from .router import RouterTable
from .registry import ServiceRegistry
from .proxy import forward_request, close_shared_client
from .metrics import REQ_COUNT, REQ_LATENCY, metrics_response
from .middleware import Middleware, MiddlewarePipeline

logger = logging.getLogger(__name__)


def create_app(
    router_table: RouterTable,
    registry: ServiceRegistry,
    metrics_enabled: bool = False,
    metrics_path: str = "/metrics",
    middleware_map: Optional[dict[str, Middleware]] = None,
    access_log: bool = True,
) -> Starlette:
    """Create the main Starlette ASGI application.

    Args:
        router_table: Configured routing table.
        registry: Service registry with backend servers.
        metrics_enabled: Whether to expose /metrics endpoint.
        metrics_path: Path for the Prometheus metrics endpoint.
        middleware_map: Named middleware instances keyed by name.
        access_log: Whether to log each request.
    """
    middleware_map = middleware_map or {}

    async def handle(request: Request) -> Response:
        start = time.perf_counter()

        router = router_table.match(request)
        if not router:
            return PlainTextResponse("No route matched", status_code=404)

        service = registry.get_service(router.service)
        backend = service.balancer.next_backend()
        if not backend:
            return PlainTextResponse("No healthy backend", status_code=503)

        # Build per-router middleware pipeline
        async def final_handler(req: Request) -> Response:
            return await forward_request(req, backend.url)

        if router.middlewares:
            pipeline = MiddlewarePipeline()
            for mw_name in router.middlewares:
                mw = middleware_map.get(mw_name)
                if mw:
                    pipeline.add(mw)
                else:
                    logger.warning("Middleware '%s' referenced by router '%s' not found", mw_name, router.name)
            chain = pipeline.build_chain(final_handler)
            resp = await chain(request)
        else:
            resp = await final_handler(request)

        duration = time.perf_counter() - start

        # Record metrics
        REQ_COUNT.labels(
            router=router.name,
            service=router.service,
            method=request.method,
            status=str(resp.status_code),
        ).inc()
        REQ_LATENCY.labels(
            router=router.name,
            service=router.service,
        ).observe(duration)

        # Access log
        if access_log:
            client = request.client.host if request.client else "-"
            logger.info(
                '%s %s %s → %s %d (%.3fs)',
                client, request.method, request.url.path,
                router.service, resp.status_code, duration,
            )

        return resp

    routes = [
        Route("/{path:path}", endpoint=handle, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]),
    ]

    if metrics_enabled:
        async def metrics_endpoint(request: Request):
            return metrics_response()
        routes.insert(0, Route(metrics_path, endpoint=metrics_endpoint, methods=["GET"]))

    async def on_shutdown():
        await close_shared_client()

    app = Starlette(routes=routes, on_shutdown=[on_shutdown])
    return app
