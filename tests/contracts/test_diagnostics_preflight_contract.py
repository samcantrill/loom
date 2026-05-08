"""Contract tests for public diagnostics preflight models."""

from __future__ import annotations

import pytest

from loom.diagnostics import (
    PreflightCheckResult,
    PreflightCheckStatus,
    PreflightGroup,
    PreflightResult,
    PreflightSeverity,
    PreflightStatus,
)
from loom.diagnostics.models import DEFAULT_PREFLIGHT_GROUPS, STABLE_CHECK_IDS


pytestmark = pytest.mark.contract


def test_public_status_group_and_check_id_values_are_stable() -> None:
    assert [status.value for status in PreflightCheckStatus] == ["PASS", "WARN", "FAIL", "SKIP"]
    assert [status.value for status in PreflightStatus] == ["PASS", "WARN", "FAIL", "SKIP"]
    assert [severity.value for severity in PreflightSeverity] == ["INFO", "WARNING", "ERROR"]
    assert [group.value for group in DEFAULT_PREFLIGHT_GROUPS] == [
        "config",
        "pipeline",
        "selectors",
        "runtime",
        "run",
        "artifacts",
        "codecs",
        "executor",
        "resources",
        "filesystem",
    ]
    assert STABLE_CHECK_IDS == {
        PreflightGroup.CONFIG: ("config.load",),
        PreflightGroup.PIPELINE: ("pipeline.graph",),
        PreflightGroup.SELECTORS: ("selectors.validate",),
        PreflightGroup.RUNTIME: (
            "runtime.options",
            "runtime.profile",
            "runtime.slurm.options",
            "runtime.stage_options",
        ),
        PreflightGroup.RUN: (
            "run_uri.resolve",
            "run_uri.slurm.local",
            "run_uri.slurm.active_submission",
        ),
        PreflightGroup.ARTIFACTS: ("artifact_store.available",),
        PreflightGroup.CODECS: ("codec_registry.available",),
        PreflightGroup.EXECUTOR: (
            "executor.local",
            "executor.resolve",
            "executor.capabilities",
            "executor.slurm.mode",
            "executor.slurm.launcher",
            "executor.slurm.sbatch",
            "executor.slurm.squeue",
            "executor.slurm.sacct",
            "executor.slurm.scancel",
            "executor.subprocess.python",
            "executor.subprocess.worker",
        ),
        PreflightGroup.RESOURCES: ("resources.capabilities", "resources.slurm.mapping"),
        PreflightGroup.FILESYSTEM: (
            "filesystem.input_exists",
            "filesystem.slurm.generated_paths",
            "filesystem.slurm.generated_writable",
        ),
    }


def test_check_result_plain_data_schema_is_stable() -> None:
    result = PreflightCheckResult(
        check_id="run_uri.resolve",
        group=PreflightGroup.RUN,
        status=PreflightCheckStatus.SKIP,
        severity=PreflightSeverity.INFO,
        message="missing run URI",
        details={"reason": "missing_run_uri"},
    )

    assert result.to_dict() == {
        "check_id": "run_uri.resolve",
        "group": "run",
        "status": "SKIP",
        "severity": "INFO",
        "message": "missing run URI",
        "details": {"reason": "missing_run_uri"},
    }


def test_preflight_result_plain_data_schema_is_stable() -> None:
    check = PreflightCheckResult(
        check_id="codec_registry.available",
        group=PreflightGroup.CODECS,
        status=PreflightCheckStatus.PASS,
        severity=PreflightSeverity.INFO,
        message="registry available",
        details={"registered": ["json.v1"]},
    )
    result = PreflightResult(checks=(check,), groups=(PreflightGroup.CODECS,))

    assert result.to_dict() == {
        "status": "PASS",
        "groups": ["codecs"],
        "checks": [
            {
                "check_id": "codec_registry.available",
                "group": "codecs",
                "status": "PASS",
                "severity": "INFO",
                "message": "registry available",
                "details": {"registered": ["json.v1"]},
            }
        ],
    }
