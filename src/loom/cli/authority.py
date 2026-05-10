"""CLI authority configuration helpers."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from typing import Any

from loom.pipeline.stores import (
    AuthorityBackendKind,
    AuthorityConfig,
    AuthorityConfigError,
    AuthorityDeploymentProfile,
    authority_config_from_mapping,
    authority_config_to_cli_args,
)
from loom.serialization import PlainData


def add_authority_options(parser: argparse.ArgumentParser) -> None:
    """Add shared authority-selection options to a command parser."""

    parser.add_argument(
        "--authority-backend",
        choices=[kind.value for kind in AuthorityBackendKind],
        help="authority backend kind",
    )
    parser.add_argument(
        "--authority-profile",
        choices=[profile.value for profile in AuthorityDeploymentProfile],
        help="authority deployment profile",
    )
    parser.add_argument(
        "--authority-endpoint",
        metavar="ENDPOINT",
        help="authority service endpoint",
    )
    parser.add_argument(
        "--authority-workspace",
        metavar="ID",
        help="authority workspace identifier",
    )
    parser.add_argument(
        "--authority-state",
        metavar="PATH",
        help="authority state reference",
    )
    parser.add_argument(
        "--authority-reference",
        metavar="ID",
        help="authority reference id",
    )
    parser.add_argument(
        "--authority-metadata-json",
        metavar="JSON",
        help=argparse.SUPPRESS,
    )


def authority_config_from_namespace(namespace: Any) -> AuthorityConfig:
    """Resolve authority config from CLI options and environment."""

    try:
        return authority_config_from_mapping(
            backend_kind=getattr(namespace, "authority_backend", None),
            deployment_profile=getattr(namespace, "authority_profile", None),
            endpoint=getattr(namespace, "authority_endpoint", None),
            workspace_id=getattr(namespace, "authority_workspace", None),
            state_path=getattr(namespace, "authority_state", None),
            reference_id=getattr(namespace, "authority_reference", None),
            metadata_json=getattr(namespace, "authority_metadata_json", None),
        )
    except AuthorityConfigError as exc:
        from loom.cli.errors import CliError, ExitCode

        raise CliError(
            f"authority configuration is invalid: {exc}",
            code="cli.authority.invalid_config",
            context={"error": str(exc)},
            exit_code=ExitCode.CONFIG,
        ) from exc


def authority_config_to_worker_args(config: AuthorityConfig) -> tuple[str, ...]:
    """Return CLI args for worker/submitted-job handoff commands."""

    return authority_config_to_cli_args(config)


def authority_metadata_summary(config: AuthorityConfig) -> Mapping[str, PlainData]:
    """Return a redacted metadata summary for CLI result contexts."""

    return config.redacted_dict()


__all__ = [
    "add_authority_options",
    "authority_config_from_namespace",
    "authority_config_to_worker_args",
    "authority_metadata_summary",
]
