"""Contracts for public SLURM dry-run CLI output."""

from __future__ import annotations

import json

import pytest

from loom.cli.formatting import format_json_envelope, format_slurm_dry_run_text
from loom.cli.results import CliWarning, SlurmDryRunCliResult

pytestmark = pytest.mark.contract


def test_slurm_dry_run_result_json_schema_is_stable() -> None:
    warning = CliWarning(
        code="executor.slurm.sbatch",
        message="sbatch is not available",
        details={"available": False},
    )
    result = SlurmDryRunCliResult(
        run_uri="file:///runs/demo",
        mode="slurm-afterok",
        planning_id="planning-1",
        manifest_path="/runs/demo/slurm/submissions/planning-1/manifest.json",
        manifest_relative_path="slurm/submissions/planning-1/manifest.json",
        plan_path="/runs/demo/slurm/submissions/planning-1/plan.json",
        plan_relative_path="slurm/submissions/planning-1/plan.json",
        script_directory="/runs/demo/slurm/submissions/planning-1/scripts",
        script_count=2,
        script_paths=(
            {
                "logical_key": "stage:build",
                "relative_path": "slurm/submissions/planning-1/scripts/stage-build.sh",
                "path": "/runs/demo/slurm/submissions/planning-1/scripts/stage-build.sh",
            },
        ),
        log_paths=(
            {
                "logical_key": "stage:build",
                "stdout_relative_path": "slurm/submissions/planning-1/logs/stage-build.stdout.log",
                "stderr_relative_path": "slurm/submissions/planning-1/logs/stage-build.stderr.log",
            },
        ),
        job_count=2,
        dependency_count=1,
        generated_commands=(
            {"logical_key": "stage:build", "argv": ["loom", "stage-job", "run"]},
        ),
        resource_summary={"stage:build": {"cpu": {"amount": 2}}},
        generated_artifact_count=4,
        preflight_warnings=(warning.to_dict(),),
    )

    payload = json.loads(
        format_json_envelope(
            schema_version="loom.cli.slurm_dry_run.v1",
            ok=True,
            warnings=(warning,),
            payload_name="result",
            payload=result.to_dict(),
        )
    )

    assert payload["schema_version"] == "loom.cli.slurm_dry_run.v1"
    assert payload["result"] == {
        "run_uri": "file:///runs/demo",
        "mode": "slurm-afterok",
        "dry_run": True,
        "planning_id": "planning-1",
        "manifest_path": "/runs/demo/slurm/submissions/planning-1/manifest.json",
        "manifest_relative_path": "slurm/submissions/planning-1/manifest.json",
        "plan_path": "/runs/demo/slurm/submissions/planning-1/plan.json",
        "plan_relative_path": "slurm/submissions/planning-1/plan.json",
        "script_directory": "/runs/demo/slurm/submissions/planning-1/scripts",
        "script_count": 2,
        "script_paths": [
            {
                "logical_key": "stage:build",
                "relative_path": "slurm/submissions/planning-1/scripts/stage-build.sh",
                "path": "/runs/demo/slurm/submissions/planning-1/scripts/stage-build.sh",
            }
        ],
        "log_paths": [
            {
                "logical_key": "stage:build",
                "stdout_relative_path": "slurm/submissions/planning-1/logs/stage-build.stdout.log",
                "stderr_relative_path": "slurm/submissions/planning-1/logs/stage-build.stderr.log",
            }
        ],
        "job_count": 2,
        "dependency_count": 1,
        "generated_commands": [
            {"logical_key": "stage:build", "argv": ["loom", "stage-job", "run"]}
        ],
        "resource_summary": {"stage:build": {"cpu": {"amount": 2}}},
        "generated_artifact_count": 4,
        "preflight_warnings": [
            {
                "code": "executor.slurm.sbatch",
                "message": "sbatch is not available",
                "details": {"available": False},
            }
        ],
    }
    assert payload["warnings"][0]["code"] == "executor.slurm.sbatch"


def test_slurm_dry_run_text_is_path_oriented_and_omits_script_bodies() -> None:
    result = SlurmDryRunCliResult(
        run_uri="file:///runs/demo",
        mode="slurm-single-job",
        planning_id="planning-1",
        manifest_path="/runs/demo/slurm/submissions/planning-1/manifest.json",
        manifest_relative_path="slurm/submissions/planning-1/manifest.json",
        plan_path="/runs/demo/slurm/submissions/planning-1/plan.json",
        plan_relative_path="slurm/submissions/planning-1/plan.json",
        script_directory="/runs/demo/slurm/submissions/planning-1/scripts",
        script_count=1,
        log_paths=(
            {
                "logical_key": "pipeline",
                "stdout_relative_path": "slurm/submissions/planning-1/logs/pipeline.stdout.log",
                "stderr_relative_path": "slurm/submissions/planning-1/logs/pipeline.stderr.log",
            },
        ),
        job_count=1,
        dependency_count=0,
    )

    text = format_slurm_dry_run_text(result)

    assert "OK slurm dry-run file:///runs/demo: slurm-single-job" in text
    assert "manifest: /runs/demo/slurm/submissions/planning-1/manifest.json" in text
    assert "logs: stdout=slurm/submissions/planning-1/logs/pipeline.stdout.log" in text
    assert "stderr=slurm/submissions/planning-1/logs/pipeline.stderr.log" in text
    assert "#SBATCH" not in text
    assert "set -euo pipefail" not in text
