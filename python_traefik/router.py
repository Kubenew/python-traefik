from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from starlette.requests import Request

from .rules import Rule, parse_rule


@dataclass
class Router:
    name: str
    rule: Rule
    service: str


class RouterTable:
    def __init__(self):
        self.routers: List[Router] = []

    def add_router(self, name: str, rule: str, service: str):
        self.routers.append(Router(name=name, rule=parse_rule(rule), service=service))

    def match(self, request: Request) -> Optional[Router]:
        for r in self.routers:
            if r.rule.matcher(request):
                return r
        return None
