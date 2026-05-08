from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .balancer import Backend, RoundRobinBalancer


@dataclass
class Service:
    name: str
    balancer: RoundRobinBalancer


class ServiceRegistry:
    def __init__(self):
        self.services: Dict[str, Service] = {}

    def register_service(self, name: str, servers: List[str]):
        backends = [Backend(url=s) for s in servers]
        self.services[name] = Service(name=name, balancer=RoundRobinBalancer(backends))

    def get_service(self, name: str) -> Service:
        if name not in self.services:
            raise KeyError(f"Service not found: {name}")
        return self.services[name]

    def all_backends(self) -> List[Backend]:
        out: List[Backend] = []
        for svc in self.services.values():
            out.extend(svc.balancer.backends)
        return out
