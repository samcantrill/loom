"""Unit coverage for CLI authority helpers and lifecycle commands."""

from __future__ import annotations

import json
import argparse
import io
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


def test_authority_import_offline_reports_unreadable_manifest_with_config_error(
    tmp_path: Path,
) -> None:
    missing_manifest = tmp_path / "missing.json"
    stdout = io.StringIO()

    exit_code = main(
        [
            "authority",
            "import-offline",
            str(missing_manifest),
            "--format",
            "json",
        ],
        stdout=stdout,
    )
    payload = json.loads(stdout.getvalue())

    assert exit_code == 3
    assert payload["ok"] is False
    assert payload["error"]["code"] == "cli.authority.offline_import_manifest_unreadable"


def test_authority_import_offline_reports_invalid_manifest_with_config_error(
    tmp_path: Path,
) -> None:
    invalid_manifest = tmp_path / "invalid.json"
    invalid_manifest.write_text("nope", encoding="utf-8")
    stdout = io.StringIO()

    exit_code = main(
        [
            "authority",
            "import-offline",
            str(invalid_manifest),
            "--format",
            "json",
        ],
        stdout=stdout,
    )
    payload = json.loads(stdout.getvalue())

    assert exit_code == 3
    assert payload["ok"] is False
    assert payload["error"]["code"] == "cli.authority.offline_import_manifest_invalid"


def test_doctor_reports_unavailable_for_stale_supervisor_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loom.authority.supervisor import (
        AuthorityProtocolReadiness,
        AuthoritySupervisorProcessState,
        AuthoritySupervisorReadiness,
        AuthoritySupervisorState,
        inspect_authority_supervisor,
        start_authority_supervisor,
    )

    class _FakeProcess:
        pid = 55555

        def poll(self) -> int | None:
            return None

    monkeypatch.setattr(
        "loom.cli.authority.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess(),
    )
    monkeypatch.setattr(
        "loom.authority.supervisor.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess(),
    )
    monkeypatch.setattr(
        "loom.authority.supervisor._wait_until_ready",
        lambda endpoint, *, timeout_seconds, process=None: AuthorityProtocolReadiness(),
    )

    state_dir = tmp_path / "state"
    workspace = tmp_path / "workspace"
    start_authority_supervisor(
        state_dir=state_dir,
        workspace_root=workspace,
        workspace_id="workspace-a",
    )
    state_path = tmp_path / "state" / "supervisor.json"
    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    state = AuthoritySupervisorState.from_dict(state_payload)
    stale = AuthoritySupervisorState(
        pid=state.pid + 1,
        endpoint=state.endpoint,
        state_dir=state.state_dir,
        workspace_root=state.workspace_root,
        workspace_id=state.workspace_id,
        service_generation=state.service_generation,
        host=state.host,
        port=state.port,
        started_at=state.started_at,
        updated_at=state.updated_at,
    )
    state_path.write_text(json.dumps(stale.to_dict()), encoding="utf-8")
    assert inspect_authority_supervisor(
        workspace_root=workspace, workspace_id="workspace-a"
    ) is not None

    doctor_stdout = io.StringIO()
    exit_code = main(
        [
            "authority",
            "doctor",
            "--state-dir",
            str(state_dir),
            "--workspace-root",
            str(workspace),
            "--workspace-id",
            "workspace-a",
            "--format",
            "json",
        ],
        stdout=doctor_stdout,
    )
    payload = json.loads(doctor_stdout.getvalue())

    assert exit_code == 6
    assert payload["ok"] is False
    assert payload["error"]["code"] == "cli.authority.doctor_failed"
    assert payload["error"]["context"]["result"]["process_state"] == (
        AuthoritySupervisorProcessState.STALE.value
    )
    assert payload["error"]["context"]["result"]["readiness"] == (
        AuthoritySupervisorReadiness.UNAVAILABLE.value
    )
