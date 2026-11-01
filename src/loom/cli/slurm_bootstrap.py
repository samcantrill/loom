"""Hidden fixed-bootstrap command used only by protected SLURM profiles."""

from __future__ import annotations

import argparse


def register_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser("slurm-bootstrap", help=argparse.SUPPRESS)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--request-digest", required=True)
    parser.add_argument("--config")
    parser.set_defaults(handler=handle)


def handle(namespace: argparse.Namespace) -> int:
    from loom.queue.slurm_bootstrap import SlurmBootstrapClientConfig, run_slurm_bootstrap

    run_slurm_bootstrap(
        operation_id=str(namespace.operation_id),
        request_digest=str(namespace.request_digest),
        config=None if namespace.config is None else SlurmBootstrapClientConfig.from_file(namespace.config),
    )
    return 0


__all__ = ["handle", "register_subparser"]
