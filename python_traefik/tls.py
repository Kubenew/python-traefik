from __future__ import annotations

import asyncio
import datetime
import logging
import os
import socket
import ssl
import tempfile
from dataclasses import dataclass, field
from typing import Optional

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

logger = logging.getLogger(__name__)

ACME_DIRECTORY_URL = "https://acme-v02.api.letsencrypt.org/directory"
ACME_STAGING_URL = "https://acme-staging-v02.api.letsencrypt.org/directory"


@dataclass
class Certificate:
    cert_pem: str
    key_pem: str
    domain: str
    expires: Optional[str] = None


@dataclass
class TLSConfig:
    certificates: list = field(default_factory=list)
    acme: Optional[ACMEConfig] = None
    min_version: str = "TLSv1.2"


@dataclass
class ACMEConfig:
    email: str
    domains: list = field(default_factory=list)
    staging: bool = False
    cert_dir: str = "./certs"
    challenge_type: str = "tls-alpn-01"


class CertificateStore:
    """In-memory store mapping domain names to Certificate objects."""

    def __init__(self):
        self._certs: dict[str, Certificate] = {}

    def add(self, cert: Certificate):
        self._certs[cert.domain] = cert
        if cert.domain.startswith("*."):
            # Also register the bare domain for wildcard lookups
            self._certs[cert.domain[2:]] = cert

    def get(self, domain: str) -> Optional[Certificate]:
        if domain in self._certs:
            return self._certs[domain]
        # Try wildcard match
        wildcard = "*." + ".".join(domain.split(".")[1:])
        return self._certs.get(wildcard)

    def list(self) -> list[Certificate]:
        # Deduplicate (wildcard entries share the same Certificate object)
        seen: set[str] = set()
        result: list[Certificate] = []
        for cert in self._certs.values():
            if cert.domain not in seen:
                seen.add(cert.domain)
                result.append(cert)
        return result


def load_cert_chain(cert_path: str, key_path: str) -> tuple[bytes, bytes]:
    """Read PEM-encoded certificate and key from disk."""
    with open(cert_path, "rb") as f:
        cert_pem = f.read()
    with open(key_path, "rb") as f:
        key_pem = f.read()
    return cert_pem, key_pem


def make_ssl_context(cert_pem: bytes, key_pem: bytes) -> ssl.SSLContext:
    """Build an SSLContext from PEM bytes.

    ssl.SSLContext.load_cert_chain() requires file paths, so we write
    the PEM data to secure temp files and load from there.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    # Write PEM bytes to temp files for ssl module consumption
    cert_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
    key_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
    try:
        cert_file.write(cert_pem)
        cert_file.flush()
        cert_file.close()

        key_file.write(key_pem)
        key_file.flush()
        key_file.close()

        ctx.load_cert_chain(certfile=cert_file.name, keyfile=key_file.name)
    finally:
        # Clean up temp files
        try:
            os.unlink(cert_file.name)
        except OSError:
            pass
        try:
            os.unlink(key_file.name)
        except OSError:
            pass

    return ctx


def _generate_self_signed_cert(domain: str) -> tuple[bytes, bytes]:
    """Generate a self-signed certificate for development/testing."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, domain)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(domain)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    return cert_pem, key_pem


def _acme_new_nonce(client: httpx.Client, directory_url: str) -> str:
    resp = client.head(directory_url)
    return resp.headers["replay-nonce"]


async def acme_provision(acme_cfg: ACMEConfig, store: CertificateStore) -> list[Certificate]:
    """Provision certificates via ACME (currently falls back to self-signed)."""
    logger.info("Starting ACME provisioning for domains: %s", acme_cfg.domains)
    os.makedirs(acme_cfg.cert_dir, exist_ok=True)

    certs = []
    for domain in acme_cfg.domains:
        cert_path = os.path.join(acme_cfg.cert_dir, f"{domain}.pem")
        key_path = os.path.join(acme_cfg.cert_dir, f"{domain}-key.pem")

        if os.path.exists(cert_path) and os.path.exists(key_path):
            cert_pem, key_pem = load_cert_chain(cert_path, key_path)
            cert = Certificate(cert_pem=cert_pem.decode(), key_pem=key_pem.decode(), domain=domain)
            store.add(cert)
            certs.append(cert)
            logger.info("Loaded existing cert for %s", domain)
            continue

        logger.info("Generating self-signed cert for %s (ACME full client TBD)", domain)
        cert_pem, key_pem = _generate_self_signed_cert(domain)
        with open(cert_path, "wb") as f:
            f.write(cert_pem)
        with open(key_path, "wb") as f:
            f.write(key_pem)
        cert = Certificate(cert_pem=cert_pem.decode(), key_pem=key_pem.decode(), domain=domain)
        store.add(cert)
        certs.append(cert)
    return certs
