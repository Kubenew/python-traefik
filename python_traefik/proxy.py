from __future__ import annotations

import httpx
from starlette.requests import Request
from starlette.responses import Response


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
    return {k: v for k, v in headers.items() if k.lower() not in HOP_BY_HOP_HEADERS}


async def forward_request(request: Request, backend_url: str) -> Response:
    target = backend_url.rstrip("/") + request.url.path
    if request.url.query:
        target += "?" + request.url.query

    body = await request.body()

    async with httpx.AsyncClient(follow_redirects=False, timeout=30) as client:
        resp = await client.request(
            method=request.method,
            url=target,
            headers=_filter_headers(dict(request.headers)),
            content=body,
        )

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=_filter_headers(dict(resp.headers)),
        media_type=resp.headers.get("content-type"),
    )
