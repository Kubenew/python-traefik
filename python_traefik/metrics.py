from __future__ import annotations

from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response


REQ_COUNT = Counter(
    "python_traefik_requests_total",
    "Total number of HTTP requests",
    ["router", "service", "method", "status"],
)

REQ_LATENCY = Histogram(
    "python_traefik_request_latency_seconds",
    "Request latency in seconds",
    ["router", "service"],
)


def metrics_response() -> Response:
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
