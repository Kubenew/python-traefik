# python-traefik

A production-grade, Traefik-inspired reverse proxy implemented in Python using asyncio and Starlette.

[![PyPI](https://img.shields.io/pypi/v/python-traefik)](https://pypi.org/project/python-traefik/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![CI](https://github.com/Kubenew/python-traefik/actions/workflows/ci.yml/badge.svg)](https://github.com/Kubenew/python-traefik/actions)
[![Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

## Demo

![python-traefik demo](demo.gif)

## Features

### Core (Implemented ✔)
- **Dynamic Routing** — rule-based routing with `Host()`, `PathPrefix()`, `Path()`, `HostRegexp()`, `Headers()`, `Method()`, `ClientIP()` matchers
- **Compound Rules** — combine matchers with `&&`, `||`, and parentheses: `(Host(\`a.com\`) || Host(\`b.com\`)) && PathPrefix(\`/api\`)`
- **Load Balancing** — round-robin across backend servers with health-aware selection
- **Health Checks** — periodic async health probes; unhealthy backends are automatically removed from rotation
- **Prometheus Metrics** — request count and latency histograms at `/metrics`
- **Reverse Proxy** — full HTTP forwarding with hop-by-hop header filtering and `X-Forwarded-*` injection
- **Connection Pooling** — shared `httpx.AsyncClient` for efficient backend connections

### Middleware Pipeline ✔
- **Rate Limiting** — per-IP token bucket rate limiter
- **Basic Auth** — HTTP Basic authentication
- **Circuit Breaker** — trips open after N failures, auto-recovers after timeout
- **Retry** — configurable retry with exponential back-off
- **Headers** — set, add, or remove response headers
- **Redirect Scheme** — HTTP → HTTPS redirect

### TCP/UDP Support ✔
- **TCP Proxy** — layer-4 TCP reverse proxy with bidirectional streaming
- **UDP Proxy** — layer-4 UDP relay with client address tracking
- **TLS Termination** — optional TLS on TCP entrypoints

### SSL/TLS Certificate Management ✔
- **Static Certificates** — load PEM cert/key from files
- **Self-Signed Generation** — auto-generate dev certs via `cryptography`
- **ACME Stub** — provisioning framework (full Let's Encrypt client TBD)
- **Certificate Store** — in-memory store with wildcard domain support

### Service Discovery ✔
- **Consul** — discover services from Consul catalog with health filtering
- **Kubernetes** — discover services from K8s API with in-cluster token auto-detection
- **Hot Reload** — discovered services update the registry without restart

### Dashboard API ✔
- **Web UI** — dark-themed dashboard at `/dashboard`
- **REST API** — JSON endpoints for overview, routers, services, and certificates
- **Real-time Status** — backend health status with visual indicators

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Entrypoint  │────▶│    Router    │────▶│  Middleware   │
│  :8000 HTTP  │     │  Rule Match  │     │   Pipeline   │
│  :3306 TCP   │     │  Priority    │     │  rate-limit  │
│  :5353 UDP   │     │              │     │  basic-auth  │
└──────────────┘     └──────────────┘     │  retry       │
                                          └──────┬───────┘
                                                 │
                     ┌──────────────┐     ┌──────▼───────┐
                     │   Backend    │◀────│ Load Balancer│
                     │  :5000       │     │ Round-Robin  │
                     │  :5001       │     │ Health-Aware │
                     └──────────────┘     └──────────────┘
```

## Quickstart

### Install

```bash
pip install -e .
```

### Install with dev dependencies

```bash
pip install -e ".[dev]"
```

### Run

```bash
python-traefik run --config examples/config.yml
```

### Validate config without starting

```bash
python-traefik validate --config examples/config.yml
```

### Check version

```bash
python-traefik version
```

### Test routing

```bash
# Route by host
curl -H "Host: example.com" http://localhost:8000/

# Prometheus metrics
curl http://localhost:8000/metrics

# Dashboard
open http://localhost:8080/dashboard

# Dashboard API
curl http://localhost:8080/api/overview
curl http://localhost:8080/api/routers
curl http://localhost:8080/api/services
```

## Configuration

See [`examples/config.yml`](examples/config.yml) for a basic setup and [`examples/config_full.yml`](examples/config_full.yml) for a full reference.

### Minimal Config

```yaml
entryPoints:
  web:
    address: ":8000"

routers:
  app:
    rule: "Host(`example.com`) && PathPrefix(`/`)"
    service: "app_service"

services:
  app_service:
    loadBalancer:
      servers:
        - url: "http://localhost:5000"
```

### Config Sections

| Section | Description |
|---|---|
| `entryPoints` | HTTP listener addresses |
| `tcpEntryPoints` | TCP proxy listeners |
| `udpEntryPoints` | UDP proxy listeners |
| `routers` | Rule → service mapping with optional middlewares and priority |
| `services` | Backend server groups with load balancer |
| `middlewares` | Named middleware definitions |
| `tls` | TLS certificates and ACME configuration |
| `metrics` | Prometheus endpoint toggle |
| `healthcheck` | Backend health probe settings |
| `dashboard` | Dashboard UI and API |
| `providers` | Service discovery (Consul, Kubernetes) |
| `logging` | Log level and access log toggle |

## Development

### Run tests

```bash
pytest tests/ -v
```

### Lint

```bash
ruff check python_traefik/
```

## License

MIT — see [LICENSE](LICENSE).
