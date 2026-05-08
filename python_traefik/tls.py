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
    def __init__(self):
        self._certs: dict[str, Certificate] = {}

    def add(self, cert: Certificate):
        self._certs[cert.domain] = cert
        if cert.domain.startswith("*."):
            self._certs[cert.domain[2:]] = cert

    def get(self, domain: str) -> Optional[Certificate]:
        if domain in self._certs:
            return self._certs[domain]
        wildcard = "*." + ".".join(domain.split(".")[1:])
        return self._certs.get(wildcard)

    def list(self) -> list[Certificate]:
        return list(self._certs.values())


def load_cert_chain(cert_path: str, key_path: str) -> tuple[bytes, bytes]:
    with open(cert_path, "rb") as f:
        cert_pem = f.read()
    with open(key_path, "rb") as f:
        key_pem = f.read()
    return cert_pem, key_pem


def make_ssl_context(cert_pem: bytes, key_pem: bytes) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert_pem, key_pem)
    return ctx


def _generate_self_signed_cert(domain: str) -> tuple[bytes, bytes]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, domain)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
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
    import datetime

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
