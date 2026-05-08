from __future__ import annotations

import time
from typing import Callable, Optional

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

from .metrics import REQ_COUNT, REQ_LATENCY, metrics_response
from .middleware import Middleware, MiddlewarePipeline
from .proxy import forward_request
from .registry import ServiceRegistry
from .router import RouterTable


def create_app(
    router_table: RouterTable,
    registry: ServiceRegistry,
    metrics_enabled: bool,
    metrics_path: str,
    middleware_pipeline: Optional[MiddlewarePipeline] = None,
    handlers: Optional[dict[str, Callable]] = None,
) -> Starlette:
    async def handle(request: Request) -> Response:
        start = time.perf_counter()

        router = router_table.match(request)
        if not router:
            return PlainTextResponse("No route matched", status_code=404)

        service = registry.get_service(router.service)
        backend = service.balancer.next_backend()
        if not backend:
            return PlainTextResponse("No healthy backend", status_code=503)

        resp = await forward_request(request, backend.url)

        duration = time.perf_counter() - start
        REQ_COUNT.labels(
            router=router.name, service=router.service,
            method=request.method, status=str(resp.status_code),
        ).inc()
        REQ_LATENCY.labels(router=router.name, service=router.service).observe(duration)

        return resp

    async def handle_with_middleware(request: Request) -> Response:
        if middleware_pipeline and middleware_pipeline._middlewares:
            chain = middleware_pipeline.build_chain(handle)
            return await chain(request)
        return await handle(request)

    routes = [
        Route(
            "/{path:path}",
            endpoint=handle_with_middleware,
            methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        ),
    ]

    if metrics_enabled:
        async def metrics_endpoint(request: Request):
            return metrics_response()
        routes.insert(0, Route(metrics_path, endpoint=metrics_endpoint, methods=["GET"]))

    app_routes = routes
    if handlers:
        for path, handler in handlers.items():
            app_routes.append(Route(path, endpoint=handler, methods=["GET"]))

    app = Starlette(routes=app_routes)
    return app
