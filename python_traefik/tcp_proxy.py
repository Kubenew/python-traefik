from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

from .balancer import RoundRobinBalancer
from .registry import ServiceRegistry

logger = logging.getLogger(__name__)


class TCPProxy:
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

    async def start(self):
        protocol_factory = lambda: self._create_protocol()
        if self.tls_context:
            self._server = await asyncio.start_server(
                protocol_factory, host=self.host, port=self.port, ssl=self.tls_context
            )
        else:
            self._server = await asyncio.start_server(
                protocol_factory, host=self.host, port=self.port
            )
        logger.info("TCP proxy listening on %s:%s (TLS=%s)", self.host, self.port, self.tls_context is not None)

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    def _create_protocol(self):
        return _TCPProxyProtocol(self.registry, self.service_name)


class _TCPProxyProtocol(asyncio.Protocol):
    def __init__(self, registry: ServiceRegistry, service_name: str):
        self.registry = registry
        self.service_name = service_name
        self._transport: Optional[asyncio.Transport] = None
        self._remote_transport: Optional[asyncio.Transport] = None
        self._remote_ready = asyncio.Event()
        self._buffer = b""

    def connection_made(self, transport: asyncio.Transport):
        self._transport = transport
        service = self.registry.get_service(self.service_name)
        backend = service.balancer.next_backend()
        if not backend:
            logger.warning("No healthy backend for %s", self.service_name)
            transport.close()
            return
        self._connect_remote(backend.url)

    def _connect_remote(self, url: str):
        host, port = _parse_tcp_addr(url)
        coro = asyncio.get_event_loop().create_connection(
            lambda: _RemoteProtocol(self), host, port
        )
        asyncio.ensure_future(self._do_connect(coro))

    async def _do_connect(self, coro):
        try:
            transport, _ = await coro
            self._remote_transport = transport
            self._remote_ready.set()
            if self._buffer:
                transport.write(self._buffer)
                self._buffer = b""
        except Exception as e:
            logger.error("Failed to connect remote: %s", e)
            if self._transport:
                self._transport.close()

    def data_received(self, data: bytes):
        if self._remote_transport:
            self._remote_transport.write(data)
        else:
            self._buffer += data

    def connection_lost(self, exc: Optional[Exception]):
        if self._remote_transport:
            self._remote_transport.close()
        self._transport = None

    def remote_closed(self):
        if self._transport:
            self._transport.close()
        self._remote_transport = None


class _RemoteProtocol(asyncio.Protocol):
    def __init__(self, client_proto: _TCPProxyProtocol):
        self._client = client_proto
        self._transport: Optional[asyncio.Transport] = None

    def connection_made(self, transport: asyncio.Transport):
        self._transport = transport

    def data_received(self, data: bytes):
        if self._client._transport:
            self._client._transport.write(data)

    def connection_lost(self, exc: Optional[Exception]):
        self._client.remote_closed()
        self._transport = None


def _parse_tcp_addr(url: str) -> tuple:
    if url.startswith("tcp://"):
        url = url[6:]
    elif url.startswith("http://"):
        url = url[7:]
    elif url.startswith("https://"):
        url = url[8:]
    host, _, port_str = url.partition(":")
    return host, int(port_str)


class UDPProxy:
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
        loop = asyncio.get_event_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _UDPProxyProtocol(self.registry, self.service_name),
            local_addr=(self.host, self.port),
        )
        logger.info("UDP proxy listening on %s:%s", self.host, self.port)

    async def stop(self):
        if self._transport:
            self._transport.close()


class _UDPProxyProtocol(asyncio.DatagramProtocol):
    def __init__(self, registry: ServiceRegistry, service_name: str):
        self.registry = registry
        self.service_name = service_name
        self._remote_transport: Optional[asyncio.DatagramTransport] = None
        self._transport: Optional[asyncio.DatagramTransport] = None

    def connection_made(self, transport: asyncio.DatagramTransport):
        self._transport = transport

    def datagram_received(self, data: bytes, addr: tuple):
        service = self.registry.get_service(self.service_name)
        backend = service.balancer.next_backend()
        if not backend:
            logger.warning("No healthy backend for UDP %s", self.service_name)
            return
        host, port = _parse_tcp_addr(backend.url)
        self._transport.sendto(data, (host, port))

    def error_received(self, exc):
        logger.error("UDP error: %s", exc)
