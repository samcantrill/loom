"""End-to-end fake-runner flow across SLURM submit, status, and cancel."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from loom.cli.main import main
from loom.pipeline.executors.slurm import FakeSlurmCommandRunner, SlurmCommandResult
from loom.pipeline.stores import path_to_run_uri

pytestmark = [pytest.mark.e2e, pytest.mark.optional_dependency]


def test_cli_slurm_live_submit_status_cancel_flow_stays_artifact_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("pydantic")
    pytest.importorskip("omegaconf")
    pytest.importorskip("yaml")

    import loom.cli.cancel as cancel_command
    import loom.cli.run as run_command
    import loom.cli.status as status_command
    import loom.diagnostics.preflight as preflight_module

    secret_value = "phase7-secret-value"
    monkeypatch.setenv("LOOM_PHASE7_SECRET_TOKEN", secret_value)
    monkeypatch.setattr(
        preflight_module.shutil,
        "which",
        lambda name: f"/usr/bin/{name}"
        if name in {"sbatch", "squeue", "sacct", "scancel"}
        else None,
    )
    submit_runner = FakeSlurmCommandRunner(starting_job_id=900)
    status_runner = FakeSlurmCommandRunner(
        scripted_results={
            "sacct": (
                SlurmCommandResult(command="sacct", argv=("sacct",), returncode=0),
            ),
            "squeue": (
                SlurmCommandResult(
                    command="squeue",
                    argv=("squeue",),
                    returncode=0,
                    stdout="900|RUNNING|None\n901|PENDING|Dependency\n",
                ),
            ),
        }
    )
    cancel_runner = FakeSlurmCommandRunner()
    monkeypatch.setattr(run_command, "_build_slurm_command_runner", lambda: submit_runner)
    monkeypatch.setattr(
        status_command,
        "_build_slurm_status_command_runner",
        lambda: status_runner,
    )
    monkeypatch.setattr(
        cancel_command,
        "_build_slurm_cancel_command_runner",
        lambda: cancel_runner,
    )
    config_path = tmp_path / "pipeline.yaml"
    _write_afterok_secret_config(config_path)
    run_path = tmp_path / "runs" / "flow"
    run_uri = path_to_run_uri(run_path)

    run_payload = _run_cli_json(
        [
            "run",
            str(config_path),
            "--executor",
            "slurm-afterok",
            "--run-uri",
            run_uri,
            "--format",
            "json",
        ],
        expected_code=0,
    )
    status_payload = _run_cli_json(
        ["status", run_uri, "--jobs", "--format", "json"],
        expected_code=0,
    )
    cancel_payload = _run_cli_json(
        ["cancel", run_uri, "--jobs", "--format", "json"],
        expected_code=0,
    )

    manifest_path = Path(run_payload["result"]["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert run_payload["result"]["status"] == "SUBMITTED"
    assert [job["scheduler_job_id"] for job in run_payload["result"]["submitted_jobs"]] == [
        "900",
        "901",
    ]
    assert status_payload["result"]["jobs"][0]["status"] == "RUNNING"
    assert status_payload["result"]["jobs"][1]["status"] == "DEPENDENCY_BLOCKED"
    assert cancel_payload["result"]["status"] == "CANCELLED"
    assert cancel_payload["result"]["cancelled_count"] == 2
    assert len(manifest["status_snapshots"]) == 2
    assert len(manifest["cancellation_attempts"]) == 2
    assert secret_value not in _read_run_text(run_path)


def _run_cli_json(argv: list[str], *, expected_code: int) -> dict[str, Any]:
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(argv, stdout=stdout, stderr=stderr) == expected_code
    assert stderr.getvalue() == ""
    return json.loads(stdout.getvalue())


def _read_run_text(run_path: Path) -> str:
    chunks: list[str] = []
    for path in sorted(item for item in run_path.rglob("*") if item.is_file()):
        chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def _write_afterok_secret_config(path: Path) -> None:
    path.write_text(
        "secret_token: ${oc.env:LOOM_PHASE7_SECRET_TOKEN}\n"
        "pipeline:\n"
        "  name: slurm-live-operations-flow\n"
        "  stages:\n"
        "    - name: extract\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.JsonProducerStage\n"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n"
        "          codec_key: json.v1\n"
        "    - name: report\n"
        "      depends_on: [extract]\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.JsonProducerStage\n"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n"
        "          codec_key: json.v1\n",
        encoding="utf-8",
    )
