# python-traefik

A minimal Traefik-like reverse proxy implemented in Python.

## Features (MVP)
- Entrypoints (HTTP listeners)
- Routers with rule parsing (Host, PathPrefix, Path)
- Services with load-balanced servers (round-robin)
- Reverse proxy forwarding (async httpx)
- Optional health checks
- Prometheus metrics endpoint

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

## Config Example
See `examples/config.yml`.
