"""Tests for the middleware pipeline."""
import asyncio

import pytest
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from python_traefik.middleware import (
    BasicAuthMiddleware,
    CircuitBreakerMiddleware,
    HeaderAction,
    HeadersMiddleware,
    MiddlewarePipeline,
    RateLimiterMiddleware,
    RedirectSchemeMiddleware,
    RetryMiddleware,
)


def _make_request(
    method: str = "GET",
    path: str = "/",
    headers: list | None = None,
    scheme: str = "http",
    client: tuple = ("127.0.0.1", 12345),
) -> Request:
    raw_headers = headers or [(b"host", b"example.com")]
    return Request({
        "type": "http",
        "method": method,
        "path": path,
        "headers": raw_headers,
        "query_string": b"",
        "server": ("127.0.0.1", 8000),
        "client": client,
        "scheme": scheme,
    })


async def _ok_handler(request: Request) -> Response:
    return PlainTextResponse("OK", status_code=200)


async def _error_handler(request: Request) -> Response:
    return PlainTextResponse("Error", status_code=500)


# --- Pipeline ---

@pytest.mark.asyncio
async def test_empty_pipeline():
    pipeline = MiddlewarePipeline()
    chain = pipeline.build_chain(_ok_handler)
    resp = await chain(_make_request())
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_pipeline_order():
    """Middlewares execute in the order they are added."""
    order = []

    class MW1(RateLimiterMiddleware):
        async def handle(self, request, call_next):
            order.append("mw1")
            return await call_next(request)

    class MW2(RateLimiterMiddleware):
        async def handle(self, request, call_next):
            order.append("mw2")
            return await call_next(request)

    pipeline = MiddlewarePipeline()
    pipeline.add(MW1())
    pipeline.add(MW2())
    chain = pipeline.build_chain(_ok_handler)
    await chain(_make_request())
    assert order == ["mw1", "mw2"]


# --- Rate Limiter ---

@pytest.mark.asyncio
async def test_rate_limiter_allows():
    mw = RateLimiterMiddleware(max_requests=5, window_seconds=1)
    for _ in range(5):
        resp = await mw.handle(_make_request(), _ok_handler)
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_rate_limiter_blocks():
    mw = RateLimiterMiddleware(max_requests=2, window_seconds=60)
    await mw.handle(_make_request(), _ok_handler)
    await mw.handle(_make_request(), _ok_handler)
    resp = await mw.handle(_make_request(), _ok_handler)
    assert resp.status_code == 429


# --- Basic Auth ---

@pytest.mark.asyncio
async def test_basic_auth_valid():
    import base64
    mw = BasicAuthMiddleware(users={"admin": "pass"})
    creds = base64.b64encode(b"admin:pass").decode()
    req = _make_request(headers=[
        (b"host", b"example.com"),
        (b"authorization", f"Basic {creds}".encode()),
    ])
    resp = await mw.handle(req, _ok_handler)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_basic_auth_missing():
    mw = BasicAuthMiddleware(users={"admin": "pass"})
    resp = await mw.handle(_make_request(), _ok_handler)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_basic_auth_wrong_password():
    import base64
    mw = BasicAuthMiddleware(users={"admin": "pass"})
    creds = base64.b64encode(b"admin:wrong").decode()
    req = _make_request(headers=[
        (b"host", b"example.com"),
        (b"authorization", f"Basic {creds}".encode()),
    ])
    resp = await mw.handle(req, _ok_handler)
    assert resp.status_code == 401


# --- Circuit Breaker ---

@pytest.mark.asyncio
async def test_circuit_breaker_opens():
    mw = CircuitBreakerMiddleware(failure_threshold=2, recovery_timeout=100.0)
    # Two failures should open the circuit
    await mw.handle(_make_request(), _error_handler)
    await mw.handle(_make_request(), _error_handler)
    # Now it should be open
    resp = await mw.handle(_make_request(), _ok_handler)
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_circuit_breaker_resets_on_success():
    mw = CircuitBreakerMiddleware(failure_threshold=3, recovery_timeout=100.0)
    await mw.handle(_make_request(), _error_handler)
    # Success resets counter
    await mw.handle(_make_request(), _ok_handler)
    await mw.handle(_make_request(), _error_handler)
    # Only 1 failure since reset, circuit should still be closed
    resp = await mw.handle(_make_request(), _ok_handler)
    assert resp.status_code == 200


# --- Retry ---

@pytest.mark.asyncio
async def test_retry_succeeds_on_first():
    mw = RetryMiddleware(attempts=3)
    resp = await mw.handle(_make_request(), _ok_handler)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_retry_exhausts():
    mw = RetryMiddleware(attempts=2)
    resp = await mw.handle(_make_request(), _error_handler)
    assert resp.status_code == 502


# --- Redirect Scheme ---

@pytest.mark.asyncio
async def test_redirect_http_to_https():
    mw = RedirectSchemeMiddleware(scheme="https", port=443)
    resp = await mw.handle(_make_request(scheme="http"), _ok_handler)
    assert resp.status_code == 302
    assert "https" in resp.headers.get("location", "")


@pytest.mark.asyncio
async def test_redirect_already_https():
    mw = RedirectSchemeMiddleware(scheme="https", port=443)
    resp = await mw.handle(_make_request(scheme="https"), _ok_handler)
    assert resp.status_code == 200
