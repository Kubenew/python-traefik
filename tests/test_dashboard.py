"""Tests for the Dashboard API endpoints."""
import pytest
from starlette.testclient import TestClient

from python_traefik.dashboard import DashboardState, create_dashboard_app
from python_traefik.registry import ServiceRegistry
from python_traefik.router import RouterTable
from python_traefik.tls import CertificateStore, Certificate


@pytest.fixture
def dashboard_client():
    registry = ServiceRegistry()
    registry.register_service("web", ["http://localhost:5000", "http://localhost:5001"])

    router_table = RouterTable()
    router_table.add_router("web_router", "Host(`example.com`)", "web")

    cert_store = CertificateStore()
    cert_store.add(Certificate(cert_pem="...", key_pem="...", domain="example.com", expires="2027-01-01"))

    state = DashboardState(
        router_table=router_table,
        registry=registry,
        cert_store=cert_store,
        providers=["file"],
        http_entrypoints=1,
        tcp_entrypoints=0,
    )
    app = create_dashboard_app(state)
    return TestClient(app)


def test_dashboard_html(dashboard_client):
    resp = dashboard_client.get("/dashboard")
    assert resp.status_code == 200
    assert "python-traefik Dashboard" in resp.text


def test_api_overview(dashboard_client):
    resp = dashboard_client.get("/api/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert data["http_entrypoints"] == 1
    assert data["router_count"] == 1
    assert data["service_count"] == 1
    assert data["cert_count"] >= 1


def test_api_routers(dashboard_client):
    resp = dashboard_client.get("/api/routers")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["routers"]) == 1
    assert data["routers"][0]["name"] == "web_router"


def test_api_services(dashboard_client):
    resp = dashboard_client.get("/api/services")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["services"]) == 1
    assert len(data["services"][0]["backends"]) == 2


def test_api_certificates(dashboard_client):
    resp = dashboard_client.get("/api/certificates")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["certificates"]) >= 1
    assert data["certificates"][0]["domain"] == "example.com"
