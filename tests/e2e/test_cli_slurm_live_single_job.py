"""End-to-end SLURM single-job live submission through the public CLI."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from loom.cli.main import main
from loom.pipeline.executors.slurm import FakeSlurmCommandRunner
from loom.pipeline.stores import LocalRunStore, path_to_run_uri

pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

pytestmark = pytest.mark.e2e


def test_cli_slurm_live_single_job_submits_with_fake_sbatch(
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
    runner = FakeSlurmCommandRunner(starting_job_id=1234)
    monkeypatch.setattr(run_command, "_build_slurm_command_runner", lambda: runner)
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(
        "pipeline:\n"
        "  name: slurm-live-e2e\n"
        "  stages:\n"
        "    - name: build\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.JsonProducerStage\n"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n"
        "          codec_key: json.v1\n",
        encoding="utf-8",
    )
    run_path = tmp_path / "runs" / "live"
    run_uri = path_to_run_uri(run_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "run",
                str(config_path),
                "--executor",
                "slurm-single-job",
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
    registry = json.loads(
        (
            run_path / "submitted_operations" / f"{result['submission_id']}.json"
        ).read_text(encoding="utf-8")
    )
    store = LocalRunStore()
    status = store.read_run_status(run_uri)

    assert stderr.getvalue() == ""
    assert payload["schema_version"] == "loom.cli.slurm_live_run.v1"
    assert payload["ok"] is True
    assert result["mode"] == "slurm-single-job"
    assert result["dry_run"] is False
    assert result["status"] == "SUBMITTED"
    assert result["submitted_jobs"][0]["scheduler_job_id"] == "1234"
    assert Path(result["plan_path"]).is_file()
    assert Path(result["manifest_path"]).is_file()
    assert manifest["dry_run"] is False
    assert manifest["submission_status"] == "SUBMITTED"
    assert manifest["submitted_jobs"][0]["scheduler_job_id"] == "1234"
    assert registry["state"] == "SUBMITTED"
    assert registry["summary_counts"]["active"] == 1
    assert status is not None
    assert status.status.value == "SUBMITTED"
    assert runner.calls[0][0] == "sbatch"
