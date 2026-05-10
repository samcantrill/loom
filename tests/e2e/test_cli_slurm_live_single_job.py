"""End-to-end SLURM single-job live authority admission through the public CLI."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from loom.cli.main import main
from loom.pipeline.executors.slurm import FakeSlurmCommandRunner
from loom.pipeline.stores import path_to_run_uri

pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

pytestmark = pytest.mark.e2e


def test_cli_slurm_live_single_job_rejects_default_authority_before_sbatch(
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
        == 7
    )

    payload = json.loads(stdout.getvalue())
    assert stderr.getvalue() == ""
    assert payload["ok"] is False
    assert payload["error"]["code"] == "cli.run.slurm_live_authority_unsupported"
    admission = payload["error"]["details"]["authority_admission"]
    assert admission["supported"] is False
    assert "slurm_live_worker" in admission["required"]
    assert runner.calls == []
    assert not run_path.exists()
