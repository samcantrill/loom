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
        "run",
        "artifacts",
        "codecs",
        "executor",
        "filesystem",
    ]
    assert STABLE_CHECK_IDS == {
        PreflightGroup.CONFIG: ("config.load",),
        PreflightGroup.PIPELINE: ("pipeline.graph",),
        PreflightGroup.SELECTORS: ("selectors.validate",),
        PreflightGroup.RUN: ("run_uri.resolve",),
        PreflightGroup.ARTIFACTS: ("artifact_store.available",),
        PreflightGroup.CODECS: ("codec_registry.available",),
        PreflightGroup.EXECUTOR: ("executor.local",),
        PreflightGroup.FILESYSTEM: ("filesystem.input_exists",),
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
