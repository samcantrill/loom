"""Unit coverage for CLI authority helpers and lifecycle commands."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pytest

from loom.cli.authority import (
    AUTHORITY_LIFECYCLE_SCHEMA_VERSION,
    add_authority_options,
    authority_resolution_mode_from_namespace,
)
from loom.cli.main import build_parser, main
from loom.pipeline.stores import AuthorityResolutionMode


pytestmark = pytest.mark.unit


def test_authority_options_can_opt_into_resolution_mode_parsing() -> None:
    parser = argparse.ArgumentParser()
    add_authority_options(parser, include_resolution_mode=True)

    namespace = parser.parse_args(["--authority-mode", "offline_first"])

    assert (
        authority_resolution_mode_from_namespace(namespace)
        is AuthorityResolutionMode.OFFLINE_FIRST
    )


def test_authority_options_default_to_existing_selection_flags_only() -> None:
    parser = argparse.ArgumentParser()
    add_authority_options(parser)

    namespace = parser.parse_args([])

    assert not hasattr(namespace, "authority_mode")
    assert (
        authority_resolution_mode_from_namespace(namespace)
        is AuthorityResolutionMode.ONLINE_MUTATION
    )


def test_offline_first_shortcut_maps_to_explicit_resolution_mode() -> None:
    parser = argparse.ArgumentParser()
    add_authority_options(parser, include_resolution_mode=True)

    namespace = parser.parse_args(["--offline-first"])

    assert (
        authority_resolution_mode_from_namespace(namespace)
        is AuthorityResolutionMode.OFFLINE_FIRST
    )


def test_authority_command_is_registered() -> None:
    parser = build_parser()

    help_text = parser.format_help()

    assert "authority" in help_text


def test_authority_start_requires_state_dir(tmp_path: Path) -> None:
    stderr = io.StringIO()

    exit_code = main(
        [
            "authority",
            "start",
            "--workspace-root",
            str(tmp_path),
            "--port",
            "8765",
        ],
        stderr=stderr,
    )

    assert exit_code == 2
    assert "--state-dir" in stderr.getvalue()


def test_authority_status_json_reports_missing_registry(tmp_path: Path) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        [
            "authority",
            "status",
            "--workspace-root",
            str(tmp_path),
            "--format",
            "json",
        ],
        stdout=stdout,
        stderr=stderr,
    )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["schema_version"] == AUTHORITY_LIFECYCLE_SCHEMA_VERSION
    assert payload["ok"] is False
    assert payload["result"]["registry_status"] == "missing"
    assert stderr.getvalue() == ""
