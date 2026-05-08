"""Tests for service discovery with mocked HTTP responses."""
import pytest

from python_traefik.discovery import (
    ConsulProvider,
    KubernetesProvider,
    DiscoveryManager,
    ProviderConfig,
)
from python_traefik.registry import ServiceRegistry


@pytest.fixture
def registry():
    return ServiceRegistry()


@pytest.mark.asyncio
async def test_discovery_manager_registers(registry):
    """DiscoveryManager._on_discover should register new services."""
    mgr = DiscoveryManager(registry)
    await mgr._on_discover({
        "web": ["http://10.0.0.1:8080", "http://10.0.0.2:8080"],
        "api": ["http://10.0.0.3:9090"],
    })
    assert registry.has_service("web")
    assert registry.has_service("api")
    assert len(registry.get_service("web").balancer.backends) == 2
    assert len(registry.get_service("api").balancer.backends) == 1


@pytest.mark.asyncio
async def test_discovery_manager_updates(registry):
    """DiscoveryManager._on_discover should update existing services."""
    registry.register_service("web", ["http://old:8080"])
    mgr = DiscoveryManager(registry)
    await mgr._on_discover({
        "web": ["http://new-1:8080", "http://new-2:8080"],
    })
    backends = registry.get_service("web").balancer.backends
    assert len(backends) == 2
    assert backends[0].url == "http://new-1:8080"


@pytest.mark.asyncio
async def test_consul_provider_handles_error():
    """ConsulProvider.discover() should return {} on network error."""
    config = ProviderConfig(type="consul", address="nonexistent:8500")
    provider = ConsulProvider(config)
    result = await provider.discover()
    assert result == {}


@pytest.mark.asyncio
async def test_kubernetes_provider_handles_error():
    """KubernetesProvider.discover() should return {} on network error."""
    config = ProviderConfig(type="kubernetes", address="https://nonexistent:6443")
    provider = KubernetesProvider(config)
    result = await provider.discover()
    assert result == {}
