"""Finite OpenSSL issuance for the trusted, same-user fleet bootstrap.

Issuer keys stay on coordinator-local storage. Requests never select certificate
extensions or signing paths. Renewal/revocation are explicit maintenance, not a
side effect of joining again.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
from pathlib import Path
import secrets
import ssl
import subprocess
import tempfile

from loom.queue.errors import QueueConfigError as FleetError
from loom.queue.deployment import _protected_input_path


def protected(path, *, private=False):
    _protected_input_path(path, label="Fleet credential", require_owner_only=private)


def openssl(*args, data=None):
    result = subprocess.run(
        ["openssl", *map(str, args)], input=data, capture_output=True, timeout=30
    )
    if result.returncode:
        raise FleetError(
            "certificate validation/issuance failed; check issuer and credential inputs"
        )
    return result.stdout


def create_file(path, data):
    """Publish a new private file, never replacing an existing credential."""
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=".issue-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def fingerprint(certificate):
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(certificate.read_text())).hexdigest()


def key_and_request(directory, name):
    key, request = directory / f"{name}.key", directory / f"{name}.csr"
    if not key.exists():
        if request.exists() or (directory / f"{name}.crt").exists():
            raise FleetError(
                "credential key is missing; recovery is required, not replacement"
            )
        create_file(
            key,
            openssl("genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072"),
        )
    protected(key, private=True)
    public = openssl("pkey", "-in", key, "-pubout")
    if not request.exists():
        create_file(
            request, openssl("req", "-new", "-key", key, "-subj", f"/CN={name}")
        )
    protected(request)
    openssl("req", "-in", request, "-verify", "-noout")
    if openssl("req", "-in", request, "-pubkey", "-noout") != public:
        raise FleetError("certificate request does not match the retained private key")
    return key, request


def validate_certificate(certificate, ca, *, request=None, key=None, hostname=None):
    for path in (certificate, ca, request, key):
        if path is not None:
            protected(path, private=path == key)
    purpose = "sslserver" if hostname else "sslclient"
    if ca is not None:
        openssl("verify", "-purpose", purpose, "-CAfile", ca, certificate)
    openssl("x509", "-in", certificate, "-checkend", "0", "-noout")
    public = openssl("x509", "-in", certificate, "-pubkey", "-noout")
    if request and openssl("req", "-in", request, "-pubkey", "-noout") != public:
        raise FleetError("issued certificate does not match the approved request")
    if key and openssl("pkey", "-in", key, "-pubout") != public:
        raise FleetError("certificate does not match the retained private key")
    if hostname:
        try:
            ipaddress.ip_address(hostname)
            flag = "-checkip"
        except ValueError:
            flag = "-checkhost"
        openssl("x509", "-in", certificate, flag, hostname, "-noout")


def ensure_ca(issuer, *, create=False):
    key, ca = issuer / "ca.key", issuer / "ca.crt"
    if not ca.exists():
        if not create:
            raise FleetError(
                "existing fleet issuer is unavailable; supply its original issuer directory"
            )
        if not key.exists():
            create_file(
                key,
                openssl(
                    "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072"
                ),
            )
        protected(key, private=True)
        create_file(
            ca,
            openssl(
                "req",
                "-new",
                "-x509",
                "-key",
                key,
                "-subj",
                "/CN=loom-fleet-ca",
                "-days",
                "3650",
                "-addext",
                "basicConstraints=critical,CA:TRUE",
                "-addext",
                "keyUsage=critical,keyCertSign,cRLSign",
            ),
        )
    for path in (key, ca):
        if not path.is_file():
            raise FleetError(
                "original CA signing material is unavailable; restore the issuer, do not replace trust"
            )
        protected(path, private=path == key)
    openssl("verify", "-CAfile", ca, ca)
    openssl("x509", "-in", ca, "-checkend", "0", "-noout")
    if openssl("x509", "-in", ca, "-pubkey", "-noout") != openssl(
        "pkey", "-in", key, "-pubout"
    ):
        raise FleetError("issuer certificate and signing key do not match")
    return ca


def issue(issuer, request, certificate, name, *, hostname=None):
    ca = ensure_ca(issuer)
    protected(request)
    openssl("req", "-in", request, "-verify", "-noout")
    if certificate.exists():
        validate_certificate(certificate, ca, request=request, hostname=hostname)
        return
    extensions = (
        "basicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature,keyEncipherment\n"
        f"extendedKeyUsage={'serverAuth' if hostname else 'clientAuth'}\n"
    )
    if hostname:
        try:
            ipaddress.ip_address(hostname)
            prefix = "IP"
        except ValueError:
            prefix = "DNS"
        extensions += f"subjectAltName={prefix}:{hostname}\n"
    with tempfile.NamedTemporaryFile(dir=issuer, prefix=".extensions-") as extension:
        extension.write(extensions.encode())
        extension.flush()
        encoded = openssl(
            "x509",
            "-req",
            "-in",
            request,
            "-CA",
            ca,
            "-CAkey",
            issuer / "ca.key",
            "-set_serial",
            str(secrets.randbits(159) or 1),
            "-days",
            "365",
            "-sha256",
            "-subj",
            f"/CN={name}",
            "-extfile",
            extension.name,
        )
    create_file(certificate, encoded)
    validate_certificate(certificate, ca, request=request, hostname=hostname)
