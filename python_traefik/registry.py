from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .balancer import Backend, RoundRobinBalancer


@dataclass
class Service:
    name: str
    balancer: RoundRobinBalancer


class ServiceRegistry:
    """Central registry of backend services and their load balancers."""

    def __init__(self):
        self.services: Dict[str, Service] = {}

    def register_service(self, name: str, servers: List[str]):
        """Register a new service with a list of backend URLs."""
        backends = [Backend(url=s) for s in servers]
        self.services[name] = Service(name=name, balancer=RoundRobinBalancer(backends))

    def has_service(self, name: str) -> bool:
        """Check if a service exists without raising."""
        return name in self.services

    def get_service(self, name: str) -> Service:
        """Get a service by name. Raises KeyError if not found."""
        if name not in self.services:
            raise KeyError(f"Service not found: {name}")
        return self.services[name]

    def update_service(self, name: str, servers: List[str]):
        """Hot-reload a service's backend list (e.g. from discovery)."""
        backends = [Backend(url=s) for s in servers]
        if name in self.services:
            self.services[name].balancer = RoundRobinBalancer(backends)
        else:
            self.register_service(name, servers)

    def all_backends(self) -> List[Backend]:
        """Return a flat list of every backend across all services."""
        out: List[Backend] = []
        for svc in self.services.values():
            out.extend(svc.balancer.backends)
        return out
