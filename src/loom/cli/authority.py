"""CLI authority configuration helpers."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

    from loom.pipeline.stores import AuthorityConfig
    from loom.pipeline.stores import AuthorityResolutionMode
    from loom.serialization import PlainData


_AUTHORITY_BACKEND_CHOICES = (
    "co_located_service",
    "managed_service",
    "allocation_scoped_service",
    "direct_database",
    "deferred_finalization",
    "test_fake",
)
_AUTHORITY_PROFILE_CHOICES = (
    "co_located",
    "managed_service",
    "allocation_scoped",
    "direct_database",
    "deferred_finalization",
)
_AUTHORITY_MODE_CHOICES = ("online_mutation", "offline_first")


def add_authority_options(
    parser: argparse.ArgumentParser,
    *,
    include_resolution_mode: bool = False,
) -> None:
    """Add shared authority-selection options to a command parser."""

    parser.add_argument(
        "--authority-backend",
        choices=_AUTHORITY_BACKEND_CHOICES,
        help="authority backend kind",
    )
    parser.add_argument(
        "--authority-profile",
        choices=_AUTHORITY_PROFILE_CHOICES,
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
    if include_resolution_mode:
        parser.add_argument(
            "--authority-mode",
            choices=_AUTHORITY_MODE_CHOICES,
            help=argparse.SUPPRESS,
        )
        parser.add_argument(
            "--offline-first",
            action="store_true",
            help=argparse.SUPPRESS,
        )


def authority_config_from_namespace(namespace: Any) -> "AuthorityConfig":
    """Resolve authority config from CLI options and environment."""

    from loom.pipeline.stores import AuthorityConfigError, authority_config_from_mapping

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


def authority_config_to_worker_args(config: "AuthorityConfig") -> tuple[str, ...]:
    """Return CLI args for worker/submitted-job handoff commands."""

    from loom.pipeline.stores import authority_config_to_cli_args

    return authority_config_to_cli_args(config)


def authority_resolution_mode_from_namespace(namespace: Any) -> "AuthorityResolutionMode":
    """Resolve authority mode from optional CLI namespace fields."""

    from loom.pipeline.stores import authority_resolution_mode_from_mapping

    return authority_resolution_mode_from_mapping(
        authority_mode=getattr(namespace, "authority_mode", None),
        offline_first=getattr(namespace, "offline_first", None),
    )


def authority_metadata_summary(config: "AuthorityConfig") -> "Mapping[str, PlainData]":
    """Return a redacted metadata summary for CLI result contexts."""

    return config.redacted_dict()


__all__ = [
    "add_authority_options",
    "authority_config_from_namespace",
    "authority_config_to_worker_args",
    "authority_metadata_summary",
    "authority_resolution_mode_from_namespace",
]
