"""Optional stdio MCP adapter for Loom's native coordinator client.

The MCP SDK is deliberately imported only when the adapter is constructed so
ordinary Loom imports do not require the ``loom[mcp]`` extra.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from collections.abc import Sequence


def create_server(*, deployment: str | Path):
    """Register tools over one protected deployment; construction does not start services."""
    from ._server import create_server as _create_server

    return _create_server(deployment=deployment)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the optional MCP stdio server with one native connection selection."""
    parser = argparse.ArgumentParser(prog="loom-mcp")
    parser.add_argument("--deployment", metavar="PATH", required=True)
    args = parser.parse_args(argv)

    try:
        from ._server import run_server
    except ModuleNotFoundError as exc:
        if exc.name == "mcp":
            print(
                "loom-mcp requires the optional MCP dependency; install loom[mcp] first.",
                file=sys.stderr,
            )
            return 1
        raise
    run_server(deployment=Path(args.deployment).resolve())
    return 0


__all__ = ["create_server", "main"]
