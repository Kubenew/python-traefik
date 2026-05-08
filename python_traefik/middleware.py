from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Optional

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class Middleware(ABC):
    name: str = "base"

    @abstractmethod
    async def handle(self, request: Request, call_next: Callable) -> Response:
        ...


class MiddlewarePipeline:
    def __init__(self, middlewares: list[Middleware] | None = None):
        self._middlewares = middlewares or []

    def add(self, mw: Middleware):
        self._middlewares.append(mw)

    def build_chain(self, handler: Callable) -> Callable:
        chain = handler
        for mw in reversed(self._middlewares):
            prev = chain
            mw_instance = mw

            async def wrapped(req: Request, _next=prev, _mw=mw_instance) -> Response:
                return await _mw.handle(req, _next)

            chain = wrapped
        return chain


class RateLimiterMiddleware(Middleware):
    name = "rate-limit"

    def __init__(self, max_requests: int = 100, window_seconds: int = 1):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._buckets: dict[str, list[float]] = {}

    async def handle(self, request: Request, call_next: Callable) -> Response:
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        window_start = now - self.window_seconds

        if key not in self._buckets:
            self._buckets[key] = []
        self._buckets[key] = [t for t in self._buckets[key] if t > window_start]

        if len(self._buckets[key]) >= self.max_requests:
            return Response("Rate limit exceeded", status_code=429)

        self._buckets[key].append(now)
        return await call_next(request)


@dataclass
class HeaderAction:
    action: str  # set, add, remove
    name: str
    value: str = ""


class HeadersMiddleware(Middleware):
    name = "headers"

    def __init__(self, actions: list[HeaderAction]):
        self.actions = actions

    async def handle(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        headers = MutableHeaders(scope=response.__dict__)
        for a in self.actions:
            if a.action == "set":
                headers[a.name] = a.value
            elif a.action == "add":
                headers.append(a.name, a.value)
            elif a.action == "remove":
                headers.pop(a.name, None)
        return response


@dataclass
class RetryMiddleware(Middleware):
    name = "retry"
    attempts: int = 3

    async def handle(self, request: Request, call_next: Callable) -> Response:
        last_exc = None
        for attempt in range(self.attempts):
            try:
                resp = await call_next(request)
                if resp.status_code < 500:
                    return resp
            except Exception as e:
                last_exc = e
                logger.warning("Retry attempt %d failed: %s", attempt + 1, e)
            await asyncio.sleep(0.1 * (attempt + 1))
        if last_exc:
            raise last_exc
        return Response("Retry failed", status_code=502)


@dataclass
class CircuitBreakerMiddleware(Middleware):
    name: circuit-breaker
    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    _failure_count: int = 0
    _last_failure: float = 0.0
    _open: bool = False

    async def handle(self, request: Request, call_next: Callable) -> Response:
        now = time.monotonic()
        if self._open:
            if now - self._last_failure > self.recovery_timeout:
                self._open = False
                self._failure_count = 0
            else:
                return Response("Circuit breaker open", status_code=503)

        response = await call_next(request)
        if response.status_code >= 500:
            self._failure_count += 1
            self._last_failure = now
            if self._failure_count >= self.failure_threshold:
                self._open = True
                logger.warning("Circuit breaker opened")
        else:
            self._failure_count = 0
        return response


class BasicAuthMiddleware(Middleware):
    name = "basic-auth"

    def __init__(self, users: dict[str, str]):
        self._users = users

    async def handle(self, request: Request, call_next: Callable) -> Response:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Basic "):
            return Response("Unauthorized", status_code=401, headers={"WWW-Authenticate": "Basic"})
        try:
            decoded = base64.b64decode(auth[6:]).decode()
            username, _, password = decoded.partition(":")
            expected = self._users.get(username)
            if expected is None or not hmac.compare_digest(expected, password):
                return Response("Unauthorized", status_code=401)
        except Exception:
            return Response("Unauthorized", status_code=401)
        return await call_next(request)


class RedirectSchemeMiddleware(Middleware):
    name = "redirect-scheme"

    def __init__(self, scheme: str = "https", port: int = 443):
        self.scheme = scheme
        self.port = port

    async def handle(self, request: Request, call_next: Callable) -> Response:
        if request.url.scheme != self.scheme:
            url = str(request.url).replace(request.url.scheme, self.scheme, 1)
            if self.port != 443:
                url = url.replace(f":{request.url.port}", f":{self.port}")
            return Response(status_code=302, headers={"Location": url})
        return await call_next(request)
