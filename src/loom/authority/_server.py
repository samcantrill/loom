"""Process entrypoint for the local authority FastAPI service."""

from __future__ import annotations

import argparse
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

    import uvicorn

    uvicorn.run(
        app,
        host=str(namespace.host),
        port=int(namespace.port),
        log_level=str(namespace.log_level),
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
