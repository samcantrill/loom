"""End-to-end smoke tests for ``loom authority`` lifecycle commands."""

from __future__ import annotations

import io
import json
import socket
from pathlib import Path

import pytest

from loom.cli.main import main


pytestmark = pytest.mark.e2e


def test_authority_supervisor_cli_lifecycle_smoke(tmp_path: Path) -> None:
    port = _free_port()
    state_dir = tmp_path / "state"
    workspace = tmp_path / "workspace"

    try:
        start_stdout = io.StringIO()
        assert (
            main(
                [
                    "authority",
                    "start",
                    "--state-dir",
                    str(state_dir),
                    "--workspace-root",
                    str(workspace),
                    "--workspace-id",
                    "workspace-a",
                    "--port",
                    str(port),
                    "--format",
                    "json",
                ],
                stdout=start_stdout,
            )
            == 0
        )
        start_payload = json.loads(start_stdout.getvalue())
        assert start_payload["ok"] is True
        assert start_payload["result"]["readiness"] == "ready"

        status_stdout = io.StringIO()
        assert (
            main(
                [
                    "authority",
                    "status",
                    "--workspace-root",
                    str(workspace),
                    "--format",
                    "json",
                ],
                stdout=status_stdout,
            )
            == 0
        )
        status_payload = json.loads(status_stdout.getvalue())
        assert status_payload["result"]["process_state"] == "running"
        assert status_payload["result"]["registry_status"] == "valid"

        doctor_stdout = io.StringIO()
        assert (
            main(
                [
                    "authority",
                    "doctor",
                    "--workspace-root",
                    str(workspace),
                    "--format",
                    "json",
                ],
                stdout=doctor_stdout,
            )
            == 0
        )
        assert json.loads(doctor_stdout.getvalue())["ok"] is True
    finally:
        stop_stdout = io.StringIO()
        main(
            [
                "authority",
                "stop",
                "--state-dir",
                str(state_dir),
                "--workspace-root",
                str(workspace),
                "--format",
                "json",
            ],
            stdout=stop_stdout,
        )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
