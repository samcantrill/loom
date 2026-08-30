"""Small OpenSSL-backed mutual-TLS fixtures shared by integration tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
import ssl
import subprocess


def mutual_tls_credentials(tmp_path: Path) -> dict[str, Path]:
    """Create one CA, one server, and two independently identified clients."""

    tmp_path.mkdir()
    _run(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        "ca.key",
        "-out",
        "ca.crt",
        "-subj",
        "/CN=loom-test-ca",
        "-days",
        "1",
        cwd=tmp_path,
    )
    for name, subject in (
        ("server", "/CN=localhost"),
        ("server-next", "/CN=localhost"),
        ("agent", "/CN=agent"),
        ("other", "/CN=other"),
        ("query", "/CN=query"),
    ):
        _run(
            "req",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            f"{name}.key",
            "-out",
            f"{name}.csr",
            "-subj",
            subject,
            cwd=tmp_path,
        )
        extension = (
            "subjectAltName=DNS:localhost"
            if name.startswith("server")
            else "extendedKeyUsage=clientAuth"
        )
        (tmp_path / f"{name}.ext").write_text(extension, encoding="utf-8")
        _run(
            "x509",
            "-req",
            "-in",
            f"{name}.csr",
            "-CA",
            "ca.crt",
            "-CAkey",
            "ca.key",
            "-CAcreateserial",
            "-out",
            f"{name}.crt",
            "-days",
            "1",
            "-sha256",
            "-extfile",
            f"{name}.ext",
            cwd=tmp_path,
        )
    return {
        name: tmp_path / name
        for name in ("ca", "server", "server-next", "agent", "other", "query")
    }


def certificate_fingerprint(certificate: Path) -> str:
    """Return the lowercase SHA-256 fingerprint of a PEM certificate's DER form."""

    return hashlib.sha256(
        ssl.PEM_cert_to_DER_cert(certificate.read_text(encoding="utf-8"))
    ).hexdigest()


def _run(*args: str, cwd: Path) -> None:
    subprocess.run(["openssl", *args], cwd=cwd, check=True, capture_output=True)


__all__ = ["certificate_fingerprint", "mutual_tls_credentials"]
