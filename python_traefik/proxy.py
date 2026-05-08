from __future__ import annotations

import logging
from typing import Optional

import httpx
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

logger = logging.getLogger(__name__)

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def _filter_headers(headers: dict) -> dict:
    """Strip hop-by-hop headers that must not be forwarded."""
    return {k: v for k, v in headers.items() if k.lower() not in HOP_BY_HOP_HEADERS}


def _inject_forwarded_headers(request: Request, headers: dict) -> dict:
    """Add standard X-Forwarded-* headers for backend awareness."""
    headers = dict(headers)  # copy
    client_host = request.client.host if request.client else "unknown"
    # Append to existing X-Forwarded-For chain
    existing_xff = headers.get("x-forwarded-for", "")
    headers["x-forwarded-for"] = f"{existing_xff}, {client_host}".lstrip(", ")
    headers["x-forwarded-host"] = headers.get("host", "")
    headers["x-forwarded-proto"] = request.url.scheme
    return headers


# ---------------------------------------------------------------------------
# Shared client management — create once, reuse for all requests
# ---------------------------------------------------------------------------
_shared_client: Optional[httpx.AsyncClient] = None


async def get_shared_client() -> httpx.AsyncClient:
    """Return (and lazily create) a long-lived async HTTP client."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(30.0, connect=5.0),
            limits=httpx.Limits(max_connections=200, max_keepalive_connections=40),
        )
    return _shared_client


async def close_shared_client() -> None:
    """Gracefully close the shared client (call on shutdown)."""
    global _shared_client
    if _shared_client and not _shared_client.is_closed:
        await _shared_client.aclose()
        _shared_client = None


async def forward_request(request: Request, backend_url: str) -> Response:
    """Forward an incoming request to a backend server."""
    target = backend_url.rstrip("/") + request.url.path
    if request.url.query:
        target += "?" + request.url.query

    body = await request.body()

    outgoing_headers = _filter_headers(dict(request.headers))
    outgoing_headers = _inject_forwarded_headers(request, outgoing_headers)

    client = await get_shared_client()
    try:
        resp = await client.request(
            method=request.method,
            url=target,
            headers=outgoing_headers,
            content=body,
        )
    except httpx.ConnectError as exc:
        logger.error("Backend connection failed: %s → %s", target, exc)
        return Response("Bad Gateway", status_code=502)
    except httpx.TimeoutException as exc:
        logger.error("Backend timeout: %s → %s", target, exc)
        return Response("Gateway Timeout", status_code=504)

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=_filter_headers(dict(resp.headers)),
        media_type=resp.headers.get("content-type"),
    )
