from __future__ import annotations

import asyncio
import httpx
from typing import Optional

from .registry import ServiceRegistry


async def _check_backend(url: str, path: str, timeout_seconds: int) -> bool:
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            r = await client.get(url.rstrip("/") + path)
            return 200 <= r.status_code < 400
    except Exception:
        return False


async def healthcheck_loop(registry: ServiceRegistry, interval_seconds: int, timeout_seconds: int, path: str):
    while True:
        for backend in registry.all_backends():
            backend.healthy = await _check_backend(backend.url, path, timeout_seconds)
        await asyncio.sleep(interval_seconds)
