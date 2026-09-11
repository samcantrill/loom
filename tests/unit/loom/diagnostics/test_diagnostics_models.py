"""Unit tests for diagnostics models and group selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom.diagnostics.models import (
    ArtifactBackendPreflightTarget,
    PreflightCheckResult,
    PreflightCheckStatus,
    PreflightError,
    PreflightGroup,
    PreflightRequest,
    PreflightResult,
    PreflightSeverity,
    PreflightStatus,
    aggregate_status,
    normalize_groups,
)


pytestmark = pytest.mark.unit


def test_preflight_check_result_serializes_plain_data() -> None:
    result = PreflightCheckResult(
        check_id="config.load",
        group=PreflightGroup.CONFIG,
        status=PreflightCheckStatus.PASS,
        severity=PreflightSeverity.INFO,
        message="config composed",
        details={"stage_count": 2, "paths": ["config.yaml"]},
    )

    assert result.group is PreflightGroup.CONFIG
    assert result.status is PreflightCheckStatus.PASS
    assert result.to_dict() == {
        "check_id": "config.load",
        "group": "config",
        "status": "PASS",
        "severity": "INFO",
        "message": "config composed",
        "details": {"stage_count": 2, "paths": ["config.yaml"]},
    }


def test_preflight_check_result_rejects_object_details() -> None:
    with pytest.raises(PreflightError, match="details"):
        PreflightCheckResult(
            check_id="config.load",
            group=PreflightGroup.CONFIG,
            status=PreflightCheckStatus.PASS,
            severity=PreflightSeverity.INFO,
            message="bad details",
            details={"path": Path("config.yaml")},  # type: ignore[dict-item]
        )


def test_aggregate_status_is_deterministic() -> None:
    def check(status: PreflightCheckStatus) -> PreflightCheckResult:
        return PreflightCheckResult(
            check_id="config.load",
            group=PreflightGroup.CONFIG,
            status=status,
            severity=PreflightSeverity.INFO,
            message=status.value,
        )

    assert aggregate_status((check(PreflightCheckStatus.PASS),)) is PreflightStatus.PASS
    assert aggregate_status((check(PreflightCheckStatus.PASS), check(PreflightCheckStatus.WARN))) is PreflightStatus.WARN
    assert aggregate_status((check(PreflightCheckStatus.WARN), check(PreflightCheckStatus.FAIL))) is PreflightStatus.FAIL
    assert aggregate_status((check(PreflightCheckStatus.SKIP),)) is PreflightStatus.SKIP
    assert aggregate_status(()) is PreflightStatus.SKIP


def test_preflight_result_computes_aggregate_status() -> None:
    result = PreflightResult(
        checks=(
            PreflightCheckResult(
                check_id="config.load",
                group=PreflightGroup.CONFIG,
                status=PreflightCheckStatus.PASS,
                severity=PreflightSeverity.INFO,
                message="passed",
            ),
        ),
        groups=(PreflightGroup.CONFIG,),
    )

    assert result.status is PreflightStatus.PASS
    assert result.to_dict()["status"] == "PASS"


@pytest.mark.parametrize("status", tuple(PreflightCheckStatus))
def test_received_preflight_preserves_checks_and_verifies_aggregate(
    status: PreflightCheckStatus,
) -> None:
    check = PreflightCheckResult(
        "runtime.options", PreflightGroup.RUNTIME, status, PreflightSeverity.INFO,
        "runtime observation", {"applicability": "required", "path": "/worker/config"},
    )
    result = PreflightResult((check,), (PreflightGroup.RUNTIME,))
    assert PreflightResult.from_dict(result.to_dict()) == result
    assert PreflightCheckResult.from_dict(check.to_dict()) == check
    conflicting = result.to_dict()
    conflicting["status"] = "FAIL" if result.status is not PreflightStatus.FAIL else "PASS"
    with pytest.raises(PreflightError, match="aggregate"):
        PreflightResult.from_dict(conflicting)


def test_received_preflight_rejects_incompatible_schema() -> None:
    with pytest.raises(PreflightError, match="fields"):
        PreflightResult.from_dict({"status": "PASS", "groups": ["config"]})
    with pytest.raises(PreflightError, match="fields"):
        PreflightCheckResult.from_dict({"status": "PASS", "group": "config"})


def test_normalize_groups_preserves_default_order_and_deduplicates() -> None:
    assert normalize_groups(("executor", "config", "executor")) == (
        PreflightGroup.CONFIG,
        PreflightGroup.EXECUTOR,
    )


def test_normalize_groups_rejects_unknown_and_empty_selections() -> None:
    with pytest.raises(PreflightError, match="empty"):
        normalize_groups(())
    with pytest.raises(PreflightError, match="unknown preflight group"):
        normalize_groups(("missing",))


def test_request_normalizes_iterables_without_touching_group_policy() -> None:
    request = PreflightRequest(
        config_path="config.yaml",
        groups=(group for group in ("run", "artifacts")),
        run_uri="file:///tmp/run",
        overlays=("overlay.yaml",),
        overrides=("pipeline.name=demo",),
    )

    assert request.groups == ("run", "artifacts")
    assert request.overlays == ("overlay.yaml",)
    assert request.overrides == ("pipeline.name=demo",)


def test_request_normalizes_artifact_backend_targets() -> None:
    target = ArtifactBackendPreflightTarget(
        target_id="external-input",
        store={"kind": "object-store"},
        required_operations=("read",),
        details={"source": "fixture"},
    )

    request = PreflightRequest(
        config_path="config.yaml",
        artifact_backend_targets=(target,),
        artifact_backend_handlers={"object-store": object()},
    )

    assert request.artifact_backend_targets == (target,)
    assert request.artifact_backend_handlers["object-store"]
    assert target.to_dict()["required_operations"] == ["read"]
