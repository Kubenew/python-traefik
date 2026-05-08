from __future__ import annotations

import time
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

from .router import RouterTable
from .registry import ServiceRegistry
from .proxy import forward_request
from .metrics import REQ_COUNT, REQ_LATENCY, metrics_response


def create_app(router_table: RouterTable, registry: ServiceRegistry, metrics_enabled: bool, metrics_path: str) -> Starlette:
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
        REQ_COUNT.labels(router=router.name, service=router.service, method=request.method, status=str(resp.status_code)).inc()
        REQ_LATENCY.labels(router=router.name, service=router.service).observe(duration)

        return resp

    routes = [
        Route("/{path:path}", endpoint=handle, methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS","HEAD"]),
    ]

    if metrics_enabled:
        async def metrics_endpoint(request: Request):
            return metrics_response()
        routes.insert(0, Route(metrics_path, endpoint=metrics_endpoint, methods=["GET"]))

    app = Starlette(routes=routes)
    return app
