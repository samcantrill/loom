"""End-to-end smoke tests for ``loom authority`` lifecycle commands."""

from __future__ import annotations

import io
import json
import socket
from pathlib import Path

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

from loom.cli.main import main
from loom.pipeline.stores import LocalRunStore, path_to_run_uri, run_uri_to_path


pytestmark = [pytest.mark.e2e, pytest.mark.optional_dependency]


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

        config_path = tmp_path / "pipeline.yaml"
        config_path.write_text(
            "pipeline:\n"
            "  name: online-authority-smoke\n"
            "  stages:\n"
            "    - name: build\n"
            "      factory:\n"
            "        _target_: tests.support.pipeline_execution_stages.JsonProducerStage\n"
            "      config:\n"
            "        value: 5\n"
            "      outputs:\n"
            "        data:\n"
            "          artifact_type: json\n"
            "          codec_key: json.v1\n",
            encoding="utf-8",
        )
        run_uri = path_to_run_uri(tmp_path / "runs" / "online-authority")
        run_stdout = io.StringIO()
        assert (
            main(
                [
                    "run",
                    str(config_path),
                    "--run-uri",
                    run_uri,
                    "--authority-backend",
                    "managed_service",
                    "--authority-profile",
                    "managed_service",
                    "--authority-endpoint",
                    start_payload["result"]["endpoint"],
                    "--authority-workspace",
                    "workspace-a",
                    "--format",
                    "json",
                ],
                stdout=run_stdout,
            )
            == 0
        )
        run_payload = json.loads(run_stdout.getvalue())
        assert run_payload["result"]["status"] == "SUCCEEDED"
        assert (run_uri_to_path(run_uri) / "status.json").is_file()

        subprocess_run_uri = path_to_run_uri(
            tmp_path / "runs" / "online-authority-subprocess"
        )
        subprocess_stdout = io.StringIO()
        assert (
            main(
                [
                    "run",
                    str(config_path),
                    "--run-uri",
                    subprocess_run_uri,
                    "--executor",
                    "subprocess",
                    "--authority-backend",
                    "managed_service",
                    "--authority-profile",
                    "managed_service",
                    "--authority-endpoint",
                    start_payload["result"]["endpoint"],
                    "--authority-workspace",
                    "workspace-a",
                    "--format",
                    "json",
                ],
                stdout=subprocess_stdout,
            )
            == 0
        )
        subprocess_payload = json.loads(subprocess_stdout.getvalue())
        assert subprocess_payload["result"]["status"] == "SUCCEEDED"
        assert (
            LocalRunStore().read_stage_worker_result(
                subprocess_run_uri,
                "build",
                attempt=1,
            )
            is not None
        )
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
