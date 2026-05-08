from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .balancer import RoundRobinBalancer
from .registry import ServiceRegistry

logger = logging.getLogger(__name__)


class TCPProxy:
    """Layer-4 TCP reverse proxy using asyncio streams."""

    def __init__(
        self,
        host: str,
        port: int,
        registry: ServiceRegistry,
        service_name: str,
        tls_context: Optional[object] = None,
    ):
        self.host = host
        self.port = port
        self.registry = registry
        self.service_name = service_name
        self.tls_context = tls_context
        self._server: Optional[asyncio.AbstractServer] = None
        self._active_connections: int = 0

    async def start(self):
        """Start the TCP proxy listener."""
        kwargs = {"host": self.host, "port": self.port}
        if self.tls_context:
            kwargs["ssl"] = self.tls_context

        self._server = await asyncio.start_server(
            self._handle_connection, **kwargs
        )
        logger.info(
            "TCP proxy listening on %s:%s (TLS=%s)",
            self.host, self.port, self.tls_context is not None,
        )

    async def stop(self):
        """Stop the TCP proxy and drain active connections."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("TCP proxy on %s:%s stopped", self.host, self.port)

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        """Handle a single inbound TCP connection by proxying to a backend."""
        self._active_connections += 1
        client_addr = writer.get_extra_info("peername")
        logger.debug("TCP connection from %s", client_addr)

        service = self.registry.get_service(self.service_name)
        backend = service.balancer.next_backend()
        if not backend:
            logger.warning("No healthy backend for TCP service %s", self.service_name)
            writer.close()
            await writer.wait_closed()
            self._active_connections -= 1
            return

        host, port = _parse_tcp_addr(backend.url)
        try:
            remote_reader, remote_writer = await asyncio.open_connection(host, port)
        except Exception as e:
            logger.error("Failed to connect to backend %s:%s → %s", host, port, e)
            writer.close()
            await writer.wait_closed()
            self._active_connections -= 1
            return

        # Bidirectional pipe
        try:
            await asyncio.gather(
                _pipe(reader, remote_writer, "client→backend"),
                _pipe(remote_reader, writer, "backend→client"),
            )
        except Exception as e:
            logger.debug("TCP pipe closed: %s", e)
        finally:
            for w in (writer, remote_writer):
                try:
                    w.close()
                    await w.wait_closed()
                except Exception:
                    pass
            self._active_connections -= 1


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, label: str):
    """Copy data from reader to writer until EOF."""
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
        pass
    finally:
        try:
            if writer.can_write_eof():
                writer.write_eof()
        except Exception:
            pass


def _parse_tcp_addr(url: str) -> tuple[str, int]:
    """Parse a URL or host:port string into (host, port)."""
    for prefix in ("tcp://", "http://", "https://"):
        if url.startswith(prefix):
            url = url[len(prefix):]
            break
    # Strip trailing path
    url = url.split("/")[0]
    host, _, port_str = url.rpartition(":")
    if not host:
        host = port_str
        raise ValueError(f"Cannot parse TCP address (no port): {url}")
    return host, int(port_str)


# ---------------------------------------------------------------------------
# UDP Proxy
# ---------------------------------------------------------------------------

class UDPProxy:
    """Layer-4 UDP reverse proxy that relays datagrams to/from backends."""

    def __init__(
        self,
        host: str,
        port: int,
        registry: ServiceRegistry,
        service_name: str,
    ):
        self.host = host
        self.port = port
        self.registry = registry
        self.service_name = service_name
        self._transport: Optional[asyncio.DatagramTransport] = None

    async def start(self):
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _UDPFrontendProtocol(self.registry, self.service_name),
            local_addr=(self.host, self.port),
        )
        logger.info("UDP proxy listening on %s:%s", self.host, self.port)

    async def stop(self):
        if self._transport:
            self._transport.close()


class _UDPFrontendProtocol(asyncio.DatagramProtocol):
    """Receives datagrams from clients, forwards to backend, relays responses."""

    def __init__(self, registry: ServiceRegistry, service_name: str):
        self.registry = registry
        self.service_name = service_name
        self._transport: Optional[asyncio.DatagramTransport] = None
        # Map backend_addr → client_addr so we can relay responses
        self._client_map: dict[tuple, tuple] = {}

    def connection_made(self, transport: asyncio.DatagramTransport):
        self._transport = transport

    def datagram_received(self, data: bytes, addr: tuple):
        service = self.registry.get_service(self.service_name)
        backend = service.balancer.next_backend()
        if not backend:
            logger.warning("No healthy backend for UDP %s", self.service_name)
            return
        backend_host, backend_port = _parse_tcp_addr(backend.url)
        backend_addr = (backend_host, backend_port)

        # Remember which client sent to this backend so we can route replies
        self._client_map[backend_addr] = addr

        # Forward to backend
        if self._transport:
            self._transport.sendto(data, backend_addr)

    def error_received(self, exc):
        logger.error("UDP error: %s", exc)
