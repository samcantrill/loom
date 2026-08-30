"""Process entrypoint for the local authority FastAPI service."""

from __future__ import annotations

import argparse
import ssl
from pathlib import Path
from typing import Sequence

from ._repository import AuthorityRepository
from .app import create_authority_app
from .services import repository_authority_services


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the local authority FastAPI service."""

    namespace = build_parser().parse_args(argv)
    repository = AuthorityRepository(Path(namespace.state_dir))
    services = repository_authority_services(
        repository,
        workspace_id=str(namespace.workspace_id),
    )
    app = create_authority_app(services=services)

    tls_values = (
        namespace.tls_certificate,
        namespace.tls_private_key,
        namespace.client_ca,
    )
    if any(tls_values) and not all(tls_values):
        raise SystemExit(
            "--tls-certificate, --tls-private-key, and --client-ca are required together"
        )

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
            }
        )
    uvicorn.run(app, **options)  # type: ignore[arg-type]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
