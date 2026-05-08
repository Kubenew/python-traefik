# python-traefik

A Traefik-like reverse proxy implemented in Python.

## Features
- HTTP/HTTPS, TCP, UDP entrypoints
- Dynamic routing (Host, PathPrefix, Path rules with && / || combinators)
- Load balancing (round-robin)
- TLS/SSL termination with certificate support
- ACME (Let's Encrypt) automatic certificate provisioning
- Middleware pipeline: rate limiting, headers, retry, circuit breaker, basic auth, redirect scheme
- Service discovery: Consul, Kubernetes
- Health checks (active)
- Prometheus metrics
- Dashboard API (overview, routers, services, certificates)
- YAML configuration

## Quickstart

### Install deps (dev)
```bash
pip install -e .
```

### Run
```bash
python-traefik run --config examples/config.yml
```

### Test routing
```bash
curl -H "Host: example.com" http://localhost:8000/
```

### Dashboard
Open http://localhost:8080/dashboard in your browser.

## Config Example
See `examples/config.yml`.
