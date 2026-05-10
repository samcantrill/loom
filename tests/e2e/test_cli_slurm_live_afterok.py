"""End-to-end SLURM afterok live authority admission through the public CLI."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from loom.cli.main import main
from loom.pipeline.executors.slurm import FakeSlurmCommandRunner
from loom.pipeline.stores import path_to_run_uri

pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

pytestmark = pytest.mark.e2e


def test_cli_slurm_live_afterok_rejects_default_authority_before_sbatch(
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
        == 7
    )

    payload = json.loads(stdout.getvalue())
    _assert_slurm_live_authority_rejected(payload)
    assert stderr.getvalue() == ""
    assert runner.calls == []
    assert not run_path.exists()


def test_cli_slurm_live_afterok_rejects_before_partial_scheduler_submission(
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
    runner = FakeSlurmCommandRunner()
    monkeypatch.setattr(run_command, "_build_slurm_command_runner", lambda: runner)
    config_path = tmp_path / "pipeline.yaml"
    _write_afterok_config(config_path)
    run_path = tmp_path / "runs" / "partial-afterok"
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
        == 7
    )

    payload = json.loads(stdout.getvalue())
    _assert_slurm_live_authority_rejected(payload)
    assert stderr.getvalue() == ""
    assert runner.calls == []
    assert not run_path.exists()


def _assert_slurm_live_authority_rejected(payload: dict[str, Any]) -> None:
    assert payload["ok"] is False
    assert payload["error"]["code"] == "cli.run.slurm_live_authority_unsupported"
    admission = payload["error"]["details"]["authority_admission"]
    assert admission["supported"] is False
    assert "slurm_live_worker" in admission["required"]


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
