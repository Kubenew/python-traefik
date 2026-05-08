from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from starlette.requests import Request

from .rules import Rule, parse_rule


@dataclass
class Router:
    name: str
    rule: Rule
    service: str
    middlewares: List[str] = field(default_factory=list)
    priority: int = 0
    entrypoints: List[str] = field(default_factory=list)


class RouterTable:
    """Ordered collection of routers; first match wins."""

    def __init__(self):
        self.routers: List[Router] = []

    def add_router(
        self,
        name: str,
        rule: str,
        service: str,
        middlewares: Optional[List[str]] = None,
        priority: int = 0,
        entrypoints: Optional[List[str]] = None,
    ):
        self.routers.append(Router(
            name=name,
            rule=parse_rule(rule),
            service=service,
            middlewares=middlewares or [],
            priority=priority,
            entrypoints=entrypoints or [],
        ))
        # Keep sorted by priority descending
        self.routers.sort(key=lambda r: r.priority, reverse=True)

    def match(self, request: Request) -> Optional[Router]:
        for r in self.routers:
            if r.rule.matcher(request):
                return r
        return None
