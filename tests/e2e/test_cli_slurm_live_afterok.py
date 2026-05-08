"""End-to-end SLURM afterok live submission through the public CLI."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from loom.cli.main import main
from loom.pipeline.executors.slurm import FakeSlurmCommandRunner, SlurmCommandResult
from loom.pipeline.stores import path_to_run_uri

pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

pytestmark = pytest.mark.e2e


def test_cli_slurm_live_afterok_submits_dependency_dag_with_fake_sbatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.cli.run as run_command
    import loom.diagnostics.preflight as preflight_module

    monkeypatch.setattr(
        preflight_module.shutil,
        "which",
        lambda name: "/usr/bin/sbatch" if name == "sbatch" else None,
    )
    runner = FakeSlurmCommandRunner(starting_job_id=200)
    monkeypatch.setattr(run_command, "_build_slurm_command_runner", lambda: runner)
    config_path = tmp_path / "pipeline.yaml"
    _write_afterok_config(config_path)
    run_path = tmp_path / "runs" / "live-afterok"
    run_uri = path_to_run_uri(run_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
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
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    result = payload["result"]
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))

    assert stderr.getvalue() == ""
    assert payload["schema_version"] == "loom.cli.slurm_live_run.v1"
    assert payload["ok"] is True
    assert result["mode"] == "slurm-afterok"
    assert result["status"] == "SUBMITTED"
    assert [job["scheduler_job_id"] for job in result["submitted_jobs"]] == [
        "200",
        "201",
        "202",
    ]
    assert result["submitted_jobs"][2]["dependency_job_ids"] == ["201"]
    assert "--dependency=afterok:201" in runner.calls[2][1]
    assert manifest["submission_status"] == "SUBMITTED"
    assert manifest["submitted_jobs"][2]["dependency_job_ids"] == ["201"]


def test_cli_slurm_live_afterok_partial_submission_returns_run_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.cli.run as run_command
    import loom.diagnostics.preflight as preflight_module

    monkeypatch.setattr(
        preflight_module.shutil,
        "which",
        lambda name: "/usr/bin/sbatch" if name == "sbatch" else None,
    )
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "sbatch": (
                SlurmCommandResult(
                    command="sbatch",
                    argv=("sbatch", "--parsable", "extract.sh"),
                    returncode=0,
                    stdout="300\n",
                ),
                SlurmCommandResult(
                    command="sbatch",
                    argv=("sbatch", "--parsable", "transform.sh"),
                    returncode=1,
                    stderr="partition closed",
                ),
            )
        }
    )
    monkeypatch.setattr(run_command, "_build_slurm_command_runner", lambda: runner)
    config_path = tmp_path / "pipeline.yaml"
    _write_afterok_config(config_path)
    run_uri = path_to_run_uri(tmp_path / "runs" / "partial-afterok")
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
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
            stdout=stdout,
            stderr=stderr,
        )
        == 5
    )

    payload = json.loads(stdout.getvalue())
    result = payload["result"]
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))

    assert stderr.getvalue() == ""
    assert payload["ok"] is False
    assert result["status"] == "PARTIAL"
    assert result["submitted_jobs"][0]["scheduler_job_id"] == "300"
    assert result["failed_submissions"][0]["logical_key"] == "stage:transform"
    assert result["failed_submissions"][0]["reason"] == "partition closed"
    assert manifest["submission_status"] == "PARTIAL"
    assert manifest["failed_submissions"][0]["dependency_job_ids"] == ["300"]


def _write_afterok_config(path: Path) -> None:
    path.write_text(
        "pipeline:\n"
        "  name: slurm-live-afterok-e2e\n"
        "  stages:\n"
        "    - name: extract\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.JsonProducerStage\n"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n"
        "          codec_key: json.v1\n"
        "    - name: transform\n"
        "      depends_on: [extract]\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.JsonProducerStage\n"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n"
        "          codec_key: json.v1\n"
        "    - name: report\n"
        "      depends_on: [transform]\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.JsonProducerStage\n"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n"
        "          codec_key: json.v1\n",
        encoding="utf-8",
    )
