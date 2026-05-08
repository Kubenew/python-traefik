from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from .config import AppConfig
from .registry import ServiceRegistry
from .router import RouterTable
from .tls import CertificateStore

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>python-traefik Dashboard</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0d1117; color: #c9d1d9; padding: 20px; }
h1 { color: #58a6ff; margin-bottom: 20px; }
h2 { color: #8b949e; margin: 20px 0 10px; }
.card { background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 16px; margin-bottom: 16px; }
.card h3 { color: #58a6ff; margin-bottom: 8px; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 8px; border-bottom: 1px solid #30363d; }
th { color: #8b949e; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 12px; }
.badge-ok { background: #1b4721; color: #3fb950; }
.badge-fail { background: #49211b; color: #f85149; }
.nav { margin-bottom: 20px; }
.nav a { color: #58a6ff; text-decoration: none; margin-right: 16px; }
.nav a:hover { text-decoration: underline; }
</style>
</head>
<body>
<h1>python-traefik Dashboard</h1>
<div class="nav">
<a href="/dashboard">Overview</a>
<a href="/dashboard/routers">Routers</a>
<a href="/dashboard/services">Services</a>
<a href="/dashboard/certificates">Certificates</a>
</div>
<div id="content">Loading...</div>
<script>
async function load(path) {
  const res = await fetch('/api' + path);
  const data = await res.json();
  let html = '';
  if (path === '/overview') {
    html = '<div class="card"><h3>Status</h3><p>HTTP Entrypoints: ' + data.http_entrypoints + '</p><p>TCP Entrypoints: ' + data.tcp_entrypoints + '</p><p>Routers: ' + data.router_count + '</p><p>Services: ' + data.service_count + '</p><p>Certificates: ' + data.cert_count + '</p><p>Providers: ' + data.providers + '</p></div>';
  } else if (path === '/routers') {
    if (!data.routers || data.routers.length === 0) { html = '<div class="card">No routers configured.</div>'; }
    else {
      html = '<table><tr><th>Name</th><th>Rule</th><th>Service</th></tr>';
      data.routers.forEach(function(r) { html += '<tr><td>' + r.name + '</td><td>' + r.rule + '</td><td>' + r.service + '</td></tr>'; });
      html += '</table>';
    }
  } else if (path === '/services') {
    if (!data.services || data.services.length === 0) { html = '<div class="card">No services configured.</div>'; }
    else {
      html = '<table><tr><th>Name</th><th>Backends</th><th>Status</th></tr>';
      data.services.forEach(function(s) {
        var ok = s.backends.filter(function(b) { return b.healthy; }).length;
        var total = s.backends.length;
        html += '<tr><td>' + s.name + '</td><td>' + ok + '/' + total + '</td><td><span class="badge ' + (ok > 0 ? 'badge-ok' : 'badge-fail') + '">' + (ok > 0 ? 'Healthy' : 'Unhealthy') + '</span></td></tr>';
      });
      html += '</table>';
    }
  } else if (path === '/certificates') {
    if (!data.certificates || data.certificates.length === 0) { html = '<div class="card">No certificates loaded.</div>'; }
    else {
      html = '<table><tr><th>Domain</th><th>Expires</th></tr>';
      data.certificates.forEach(function(c) { html += '<tr><td>' + c.domain + '</td><td>' + (c.expires || 'N/A') + '</td></tr>'; });
      html += '</table>';
    }
  }
  document.getElementById('content').innerHTML = html;
}
document.querySelectorAll('.nav a').forEach(function(a) {
  a.addEventListener('click', function(e) { e.preventDefault(); load(a.getAttribute('href').replace('/dashboard', '')); });
});
load('/overview');
</script>
</body>
</html>"""


@dataclass
class DashboardState:
    router_table: RouterTable
    registry: ServiceRegistry
    cert_store: CertificateStore
    providers: list[str] = field(default_factory=list)
    http_entrypoints: int = 0
    tcp_entrypoints: int = 0


def create_dashboard_app(state: DashboardState) -> Starlette:
    async def overview(request: Request) -> JSONResponse:
        svcs = []
        for name, svc in state.registry.services.items():
            backends = [
                {"url": b.url, "healthy": b.healthy}
                for b in svc.balancer.backends
            ]
            svcs.append({"name": name, "backends": backends})

        routers = [
            {"name": r.name, "rule": r.rule.raw, "service": r.service}
            for r in state.router_table.routers
        ]

        certs = [
            {"domain": c.domain, "expires": c.expires}
            for c in state.cert_store.list()
        ]

        return JSONResponse({
            "http_entrypoints": state.http_entrypoints,
            "tcp_entrypoints": state.tcp_entrypoints,
            "router_count": len(routers),
            "service_count": len(svcs),
            "cert_count": len(certs),
            "providers": ", ".join(state.providers) if state.providers else "file",
        })

    async def routers_endpoint(request: Request) -> JSONResponse:
        routers = [
            {"name": r.name, "rule": r.rule.raw, "service": r.service}
            for r in state.router_table.routers
        ]
        return JSONResponse({"routers": routers})

    async def services_endpoint(request: Request) -> JSONResponse:
        svcs = []
        for name, svc in state.registry.services.items():
            backends = [
                {"url": b.url, "healthy": b.healthy}
                for b in svc.balancer.backends
            ]
            svcs.append({"name": name, "backends": backends})
        return JSONResponse({"services": svcs})

    async def certificates_endpoint(request: Request) -> JSONResponse:
        certs = [
            {"domain": c.domain, "expires": c.expires}
            for c in state.cert_store.list()
        ]
        return JSONResponse({"certificates": certs})

    async def dashboard_html(request: Request) -> HTMLResponse:
        return HTMLResponse(DASHBOARD_HTML)

    routes = [
        Route("/dashboard", endpoint=dashboard_html, methods=["GET"]),
        Route("/api/overview", endpoint=overview, methods=["GET"]),
        Route("/api/routers", endpoint=routers_endpoint, methods=["GET"]),
        Route("/api/services", endpoint=services_endpoint, methods=["GET"]),
        Route("/api/certificates", endpoint=certificates_endpoint, methods=["GET"]),
    ]
    return Starlette(routes=routes)
