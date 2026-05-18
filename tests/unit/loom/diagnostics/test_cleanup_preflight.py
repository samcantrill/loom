"""Unit tests for cleanup preflight diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from loom.diagnostics import (
    CleanupPreflightTarget,
    PreflightCheckStatus,
    PreflightRequest,
    PreflightStatus,
    run_preflight,
)
from loom.pipeline.cleanup import CleanupManagedRoot
from loom.pipeline.stores import (
    BackendRevision,
    CleanupCandidate,
    CleanupCandidateKind,
    LifecycleReason,
    path_to_run_uri,
)
from loom.serialization import PlainData


pytestmark = pytest.mark.unit


@dataclass(slots=True)
class CleanupPreflightStore:
    run_uri: str
    candidates: tuple[CleanupCandidate, ...]
    append_calls: int = 0

    def list_cleanup_candidates(self, run_uri: str) -> tuple[CleanupCandidate, ...]:
        assert run_uri == self.run_uri
        return self.candidates

    def append_cleanup_report(self, *_args: object, **_kwargs: object) -> object:
        self.append_calls += 1
        raise AssertionError("cleanup preflight must not append cleanup reports")

    def append_cleanup_result(self, *_args: object, **_kwargs: object) -> object:
        self.append_calls += 1
        raise AssertionError("cleanup preflight must not append cleanup results")


def test_cleanup_preflight_skips_without_explicit_targets() -> None:
    result = run_preflight(
        PreflightRequest(config_path="missing.yaml", groups=("cleanup",))
    )

    assert result.status is PreflightStatus.SKIP
    assert [check.check_id for check in result.checks] == [
        "cleanup.candidates.safety",
        "cleanup.targets.support",
        "cleanup.retention.policy",
    ]
    assert all(check.status is PreflightCheckStatus.SKIP for check in result.checks)


def test_cleanup_preflight_warns_without_mutating_authority(tmp_path: Path) -> None:
    run_root = tmp_path / "runs" / "preflight"
    safe_target = run_root / "tmp" / "safe.txt"
    missing_ownership = run_root / "tmp" / "missing-ownership.txt"
    unsupported_retention = run_root / "tmp" / "unsupported-retention.txt"
    safe_target.parent.mkdir(parents=True)
    safe_target.write_text("safe", encoding="utf-8")
    missing_ownership.write_text("missing", encoding="utf-8")
    unsupported_retention.write_text("retention", encoding="utf-8")
    run_uri = path_to_run_uri(run_root)
    store = CleanupPreflightStore(
        run_uri=run_uri,
        candidates=(
            _candidate(
                "safe",
                path_to_run_uri(safe_target),
                detail={"ownership_key": "run-r1", "retention_mode": "temporary"},
            ),
            _candidate(
                "remote",
                "s3://bucket/key",
                detail={"ownership_key": "run-r1", "retention_mode": "external"},
            ),
            _candidate("missing-ownership", path_to_run_uri(missing_ownership)),
            _candidate(
                "bad-retention",
                path_to_run_uri(unsupported_retention),
                detail={"ownership_key": "run-r1", "retention_mode": "delete-now"},
            ),
        ),
    )

    result = run_preflight(
        PreflightRequest(
            config_path="missing.yaml",
            groups=("cleanup",),
            cleanup_targets=(
                CleanupPreflightTarget(
                    target_id="run-cleanup",
                    run_uri=run_uri,
                    store=store,
                    managed_roots=(
                        CleanupManagedRoot(
                            root_id="run-root",
                            uri=path_to_run_uri(run_root),
                            ownership_key="run-r1",
                        ),
                    ),
                ),
            ),
        )
    )

    by_id = {check.check_id: check for check in result.checks}
    assert result.status is PreflightStatus.WARN
    assert by_id["cleanup.candidates.safety"].status is PreflightCheckStatus.WARN
    assert by_id["cleanup.candidates.safety"].details["unsafe_count"] == 2
    assert by_id["cleanup.targets.support"].status is PreflightCheckStatus.WARN
    assert by_id["cleanup.targets.support"].details["unsupported_target_count"] == 1
    assert by_id["cleanup.retention.policy"].status is PreflightCheckStatus.WARN
    assert by_id["cleanup.retention.policy"].details["unsupported_policy_count"] == 1
    assert store.append_calls == 0


def _candidate(
    candidate_id: str,
    uri: str,
    *,
    detail: dict[str, PlainData] | None = None,
) -> CleanupCandidate:
    return CleanupCandidate(
        candidate_id=candidate_id,
        kind=CleanupCandidateKind.STAGED_PAYLOAD,
        uri=uri,
        reason=LifecycleReason(
            code="temporary_payload",
            detail={} if detail is None else detail,
        ),
        recorded_at="2020-01-01T00:00:00Z",
        revision=BackendRevision(sequence=1, token=f"rev-{candidate_id}"),
    )
