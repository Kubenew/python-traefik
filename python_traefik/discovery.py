from __future__ import annotations

import abc
import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

import httpx

from .balancer import Backend, RoundRobinBalancer
from .registry import ServiceRegistry

logger = logging.getLogger(__name__)


@dataclass
class ProviderConfig:
    type: str  # consul, kubernetes
    address: str = ""
    token: str = ""
    scheme: str = "http"
    namespace: str = "default"
    labels: dict = field(default_factory=dict)
    poll_interval: int = 30


class ServiceDiscoveryProvider(abc.ABC):
    @abc.abstractmethod
    async def discover(self) -> dict[str, list[str]]:
        ...

    @abc.abstractmethod
    async def watch(self, callback: Callable):
        ...


class ConsulProvider(ServiceDiscoveryProvider):
    def __init__(self, config: ProviderConfig):
        self.config = config
        self._base_url = f"{config.scheme}://{config.address}"

    async def discover(self) -> dict[str, list[str]]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                headers = {"X-Consul-Token": self.config.token} if self.config.token else {}
                resp = await client.get(f"{self._base_url}/v1/catalog/services", headers=headers)
                resp.raise_for_status()
                services = resp.json()
                result: dict[str, list[str]] = {}
                for svc_name in services:
                    svc_resp = await client.get(
                        f"{self._base_url}/v1/health/service/{svc_name}?passing",
                        headers=headers,
                    )
                    svc_resp.raise_for_status()
                    instances = svc_resp.json()
                    urls = []
                    for inst in instances:
                        svc = inst.get("Service", {})
                        addr = svc.get("Address") or inst.get("Node", {}).get("Address", "")
                        port = svc.get("Port", 0)
                        if addr and port:
                            urls.append(f"http://{addr}:{port}")
                    if urls:
                        result[svc_name] = urls
                return result
        except Exception as e:
            logger.error("Consul discovery failed: %s", e)
            return {}

    async def watch(self, callback: Callable):
        while True:
            services = await self.discover()
            await callback(services)
            await asyncio.sleep(self.config.poll_interval)


class KubernetesProvider(ServiceDiscoveryProvider):
    def __init__(self, config: ProviderConfig):
        self.config = config

    async def discover(self) -> dict[str, list[str]]:
        try:
            base = self.config.address or "https://kubernetes.default.svc"
            async with httpx.AsyncClient(timeout=10, verify=False) as client:
                headers = {"Authorization": f"Bearer {self.config.token}"} if self.config.token else {}
                ns = self.config.namespace
                resp = await client.get(
                    f"{base}/api/v1/namespaces/{ns}/services",
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
                result: dict[str, list[str]] = {}
                for item in data.get("items", []):
                    name = item["metadata"]["name"]
                    spec = item.get("spec", {})
                    if spec.get("type") == "ExternalName":
                        continue
                    cluster_ip = spec.get("clusterIP")
                    ports = spec.get("ports", [])
                    if cluster_ip and ports:
                        urls = [f"http://{cluster_ip}:{p['port']}" for p in ports]
                        result[name] = urls
                return result
        except Exception as e:
            logger.error("K8s discovery failed: %s", e)
            return {}

    async def watch(self, callback: Callable):
        while True:
            services = await self.discover()
            await callback(services)
            await asyncio.sleep(self.config.poll_interval)


class DiscoveryManager:
    def __init__(self, registry: ServiceRegistry):
        self.registry = registry
        self._providers: list[ServiceDiscoveryProvider] = []
        self._tasks: list[asyncio.Task] = []

    def add_provider(self, provider: ServiceDiscoveryProvider):
        self._providers.append(provider)

    async def start(self):
        for provider in self._providers:
            task = asyncio.create_task(provider.watch(self._on_discover))
            self._tasks.append(task)
        logger.info("Discovery manager started with %d providers", len(self._providers))

    async def stop(self):
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _on_discover(self, services: dict[str, list[str]]):
        for svc_name, urls in services.items():
            if self.registry.get_service(svc_name):
                backends = [Backend(url=u) for u in urls]
                self.registry.services[svc_name].balancer = RoundRobinBalancer(backends)
                logger.info("Updated service %s with %d backends", svc_name, len(urls))
            else:
                self.registry.register_service(svc_name, urls)
                logger.info("Registered discovered service %s with %d backends", svc_name, len(urls))
