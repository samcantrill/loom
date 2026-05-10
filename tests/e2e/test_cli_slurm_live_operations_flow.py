"""End-to-end fake-runner coverage for SLURM live authority admission."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from loom.cli.main import main
from loom.pipeline.executors.slurm import FakeSlurmCommandRunner
from loom.pipeline.stores import path_to_run_uri

pytestmark = [pytest.mark.e2e, pytest.mark.optional_dependency]


def test_cli_slurm_live_submit_status_cancel_flow_stays_artifact_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("pydantic")
    pytest.importorskip("omegaconf")
    pytest.importorskip("yaml")

    import loom.cli.run as run_command
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
    monkeypatch.setattr(run_command, "_build_slurm_command_runner", lambda: submit_runner)
    config_path = tmp_path / "pipeline.yaml"
    _write_afterok_secret_config(config_path)
    run_path = tmp_path / "runs" / "flow"
    run_uri = path_to_run_uri(run_path)

    payload = _run_cli_json(
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
        expected_code=7,
    )

    assert payload["error"]["code"] == "cli.run.slurm_live_authority_unsupported"
    assert payload["error"]["details"]["authority_admission"]["supported"] is False
    assert submit_runner.calls == []
    assert not run_path.exists()
    assert secret_value not in _read_run_text(run_path)


def _run_cli_json(argv: list[str], *, expected_code: int) -> dict[str, Any]:
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(argv, stdout=stdout, stderr=stderr) == expected_code
    assert stderr.getvalue() == ""
    return json.loads(stdout.getvalue())


def _read_run_text(run_path: Path) -> str:
    chunks: list[str] = []
    if not run_path.exists():
        return ""
    for path in sorted(item for item in run_path.rglob("*") if item.is_file()):
        try:
            chunks.append(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            continue
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
