"""Contract tests for ``loom preflight`` CLI output."""

from __future__ import annotations

import json

import pytest

from loom.cli.formatting import format_json_envelope
from loom.cli.preflight import PREFLIGHT_RESULT_SCHEMA_VERSION
from loom.diagnostics import (
    PreflightCheckResult,
    PreflightCheckStatus,
    PreflightGroup,
    PreflightResult,
    PreflightSeverity,
)
from loom.diagnostics.models import STABLE_CHECK_IDS


pytestmark = pytest.mark.contract


def test_preflight_json_result_envelope_contract() -> None:
    result = PreflightResult(
        checks=(
            PreflightCheckResult(
                check_id="config.load",
                group=PreflightGroup.CONFIG,
                status=PreflightCheckStatus.FAIL,
                severity=PreflightSeverity.ERROR,
                message="config composition failed",
                details={"error_type": "ConfigError", "error": "bad config"},
            ),
        ),
        groups=(PreflightGroup.CONFIG,),
    )

    payload = json.loads(
        format_json_envelope(
            schema_version=PREFLIGHT_RESULT_SCHEMA_VERSION,
            ok=False,
            warnings=[],
            payload_name="result",
            payload=result.to_dict(),
        )
    )

    assert payload == {
        "schema_version": "loom.cli.preflight.v3",
        "ok": False,
        "warnings": [],
        "result": {
            "status": "FAIL",
            "groups": ["config"],
            "checks": [
                {
                    "check_id": "config.load",
                    "group": "config",
                    "status": "FAIL",
                    "severity": "ERROR",
                    "message": "config composition failed",
                    "details": {
                        "error_type": "ConfigError",
                        "error": "bad config",
                    },
                }
            ],
        },
    }


def test_preflight_slurm_check_ids_are_stable() -> None:
    assert "run_uri.slurm.active_submission" in STABLE_CHECK_IDS[PreflightGroup.RUN]
    assert "executor.slurm.sbatch" in STABLE_CHECK_IDS[PreflightGroup.EXECUTOR]
    assert "executor.slurm.squeue" in STABLE_CHECK_IDS[PreflightGroup.EXECUTOR]
    assert "executor.slurm.sacct" in STABLE_CHECK_IDS[PreflightGroup.EXECUTOR]
    assert "executor.slurm.scancel" in STABLE_CHECK_IDS[PreflightGroup.EXECUTOR]
    assert (
        "filesystem.slurm.generated_writable"
        in STABLE_CHECK_IDS[PreflightGroup.FILESYSTEM]
    )


def test_preflight_docker_check_ids_are_stable() -> None:
    assert "executor.docker.command" in STABLE_CHECK_IDS[PreflightGroup.EXECUTOR]
    assert (
        "executor.docker.container_options"
        in STABLE_CHECK_IDS[PreflightGroup.EXECUTOR]
    )
    assert "executor.docker.image" in STABLE_CHECK_IDS[PreflightGroup.EXECUTOR]
    assert "executor.docker.environment" in STABLE_CHECK_IDS[PreflightGroup.EXECUTOR]
    assert "resources.docker.mapping" in STABLE_CHECK_IDS[PreflightGroup.RESOURCES]
    assert "resources.docker.gpu" in STABLE_CHECK_IDS[PreflightGroup.RESOURCES]
    assert (
        "filesystem.docker.artifact_root_visible"
        in STABLE_CHECK_IDS[PreflightGroup.FILESYSTEM]
    )
