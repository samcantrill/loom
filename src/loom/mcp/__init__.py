"""Optional stdio MCP adapter for Loom's native coordinator client.

The MCP SDK is deliberately imported only when the adapter is constructed so
ordinary Loom imports do not require the ``loom[mcp]`` extra.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence


def create_server(*, client: object):
    """Create an MCP server over an already selected native coordinator client."""
    from ._server import create_server as _create_server

    return _create_server(client=client)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the optional MCP stdio server with one native connection selection."""
    parser = argparse.ArgumentParser(prog="loom-mcp")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--endpoint", metavar="PATH")
    selection.add_argument("--connection", metavar="PATH")
    parser.add_argument("--expected-coordinator-id", metavar="ID")
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
    from loom.coordinator import CoordinatorClient

    if args.endpoint is not None:
        client = CoordinatorClient.from_unix_socket(
            args.endpoint, expected_coordinator_id=args.expected_coordinator_id
        )
    else:
        client = CoordinatorClient.from_connection_file(
            args.connection, expected_coordinator_id=args.expected_coordinator_id
        )
    run_server(client=client)
    return 0


__all__ = ["create_server", "main"]
