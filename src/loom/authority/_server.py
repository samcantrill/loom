"""Process entrypoint for the local authority FastAPI service."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import ssl
from pathlib import Path
from typing import Awaitable, Callable, Sequence

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from uvicorn.protocols.http.h11_impl import H11Protocol

from loom.pipeline.stores.coordinator_authority import (
    COORDINATOR_AUTHORITY_ROUTE_PREFIX,
)

from ._repository import AuthorityRepository
from .app import create_authority_app
from .services import (
    AUTHORITY_PEER_CERTIFICATE_FINGERPRINT_STATE_KEY,
    repository_authority_services,
)


class _PeerCertificateH11Protocol(H11Protocol):
    """Expose only the TLS-verified peer fingerprint to the ASGI application."""

    def connection_made(self, transport: asyncio.Transport) -> None:  # type: ignore[override]
        super().connection_made(transport)
        state = dict(self.app_state)
        ssl_object = transport.get_extra_info("ssl_object")
        certificate = (
            None
            if ssl_object is None
            else ssl_object.getpeercert(binary_form=True)
        )
        if isinstance(certificate, bytes) and certificate:
            state[AUTHORITY_PEER_CERTIFICATE_FINGERPRINT_STATE_KEY] = (
                hashlib.sha256(certificate).hexdigest()
            )
        self.app_state = state


def build_parser() -> argparse.ArgumentParser:
    """Build the private authority server argument parser."""

    parser = argparse.ArgumentParser(prog="python -m loom.authority._server")
    parser.add_argument("--state-dir", required=True, help="authority service state directory")
    parser.add_argument("--workspace-id", required=True, help="workspace identifier")
    parser.add_argument("--host", default="127.0.0.1", help="host interface")
    parser.add_argument("--port", type=int, required=True, help="port to bind")
    parser.add_argument("--log-level", default="warning", help="uvicorn log level")
    parser.add_argument("--tls-certificate", help="HTTPS server certificate")
    parser.add_argument("--tls-private-key", help="HTTPS server private key")
    parser.add_argument("--client-ca", help="CA used to require coordinator clients")
    parser.add_argument(
        "--coordinator-credential",
        action="append",
        default=[],
        metavar="SERVICE_ID=SHA256",
        help="map one coordinator service ID to its client-certificate fingerprint",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the local authority FastAPI service."""

    namespace = build_parser().parse_args(argv)
    tls_values = (
        namespace.tls_certificate,
        namespace.tls_private_key,
        namespace.client_ca,
    )
    if any(tls_values) and not all(tls_values):
        raise SystemExit(
            "--tls-certificate, --tls-private-key, and --client-ca are required together"
        )
    credentials = _coordinator_credentials(namespace.coordinator_credential)
    if credentials and not all(tls_values):
        raise SystemExit("--coordinator-credential requires mutual TLS")
    if all(tls_values) and not credentials:
        raise SystemExit(
            "mutual TLS coordinator authority requires --coordinator-credential"
        )

    repository = AuthorityRepository(Path(namespace.state_dir))
    services = repository_authority_services(
        repository,
        workspace_id=str(namespace.workspace_id),
        coordinator_credentials=credentials,
    )
    app = create_authority_app(services=services)
    if credentials:
        _install_coordinator_only_surface(app)

    import uvicorn

    options: dict[str, object] = {
        "host": str(namespace.host),
        "port": int(namespace.port),
        "log_level": str(namespace.log_level),
        "access_log": False,
    }
    if all(tls_values):
        options.update(
            {
                "ssl_certfile": str(namespace.tls_certificate),
                "ssl_keyfile": str(namespace.tls_private_key),
                "ssl_ca_certs": str(namespace.client_ca),
                "ssl_cert_reqs": ssl.CERT_REQUIRED,
                "http": _PeerCertificateH11Protocol,
            }
        )
    uvicorn.run(app, **options)  # type: ignore[arg-type]
    return 0


def _install_coordinator_only_surface(app: FastAPI) -> None:
    """Hide generic authority mutation APIs from coordinator credentials."""

    @app.middleware("http")
    async def coordinator_surface(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        if path != "/ready" and path != COORDINATOR_AUTHORITY_ROUTE_PREFIX and not (
            path.startswith(f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/")
        ):
            return JSONResponse(status_code=404, content={"detail": "not found"})
        return await call_next(request)


def _coordinator_credentials(values: Sequence[str]) -> dict[str, str]:
    credentials: dict[str, str] = {}
    fingerprints: set[str] = set()
    for value in values:
        service_id, separator, fingerprint = value.partition("=")
        if (
            not separator
            or not service_id
            or len(fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in fingerprint)
            or service_id in credentials
            or fingerprint in fingerprints
        ):
            raise SystemExit("--coordinator-credential must be unique SERVICE_ID=SHA256")
        credentials[service_id] = fingerprint
        fingerprints.add(fingerprint)
    return credentials


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
