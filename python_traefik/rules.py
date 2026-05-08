from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

from starlette.requests import Request


@dataclass
class Rule:
    raw: str
    matcher: Callable[[Request], bool]


def _parse_single(expr: str) -> Callable[[Request], bool]:
    expr = expr.strip()

    # Host(`example.com`)
    m = re.match(r"^Host\(`([^`]+)`\)$", expr)
    if m:
        host = m.group(1)
        def match(req: Request) -> bool:
            return (req.headers.get("host") or "").split(":")[0] == host
        return match

    # PathPrefix(`/api`)
    m = re.match(r"^PathPrefix\(`([^`]+)`\)$", expr)
    if m:
        prefix = m.group(1)
        def match(req: Request) -> bool:
            return req.url.path.startswith(prefix)
        return match

    # Path(`/exact`)
    m = re.match(r"^Path\(`([^`]+)`\)$", expr)
    if m:
        path = m.group(1)
        def match(req: Request) -> bool:
            return req.url.path == path
        return match

    raise ValueError(f"Unsupported rule expression: {expr}")


def parse_rule(rule: str) -> Rule:
    # Very small subset of Traefik rule grammar:
    #   A && B
    #   A || B
    # Parentheses not supported in MVP

    raw = rule.strip()

    if "&&" in raw:
        parts = [p.strip() for p in raw.split("&&")]
        matchers = [_parse_single(p) for p in parts]
        def matcher(req: Request) -> bool:
            return all(m(req) for m in matchers)
        return Rule(raw=raw, matcher=matcher)

    if "||" in raw:
        parts = [p.strip() for p in raw.split("||")]
        matchers = [_parse_single(p) for p in parts]
        def matcher(req: Request) -> bool:
            return any(m(req) for m in matchers)
        return Rule(raw=raw, matcher=matcher)

    matcher = _parse_single(raw)
    return Rule(raw=raw, matcher=matcher)
