"""Unit tests for collection cleanup aggregation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest

from loom.pipeline.cleanup import (
    CleanupDeleteIntent,
    CleanupError,
    CleanupManagedRoot,
    CleanupResult,
    CleanupResultOutcome,
    CollectionCleanupTarget,
    execute_collection_gc,
    plan_collection_gc,
)
from loom.pipeline.stores import (
    BackendRevision,
    CleanupCandidate,
    CleanupCandidateKind,
    CleanupResultFact,
    LifecycleReason,
    PerRunAuthorityStore,
    path_to_run_uri,
)
from loom.serialization import PlainData


pytestmark = pytest.mark.unit


@dataclass(slots=True)
class CollectionStore:
    run_uri: str
    candidates: tuple[CleanupCandidate, ...]
    results: list[CleanupResultFact] = field(default_factory=list)
    append_report_calls: int = 0

    def list_cleanup_candidates(self, run_uri: str) -> tuple[CleanupCandidate, ...]:
        assert run_uri == self.run_uri
        return self.candidates

    def append_cleanup_result(
        self,
        run_uri: str,
        result: CleanupResult,
    ) -> CleanupResultFact:
        assert run_uri == self.run_uri
        fact = CleanupResultFact(
            result=result,
            recorded_at="2020-01-01T00:00:06Z",
            revision=BackendRevision(
                sequence=len(self.results) + 1,
                token=f"rev-{len(self.results) + 1}",
            ),
        )
        self.results.append(fact)
        return fact

    def append_cleanup_report(self, *_args: object, **_kwargs: object) -> object:
        self.append_report_calls += 1
        raise AssertionError("collection dry-run must not append reports")


def test_plan_collection_gc_aggregates_per_run_reports_without_writes(
    tmp_path: Path,
) -> None:
    first_run = tmp_path / "runs" / "one"
    second_run = tmp_path / "runs" / "two"
    first_target = first_run / "tmp" / "payload.txt"
    second_target = second_run / "tmp" / "payload.txt"
    first_target.parent.mkdir(parents=True)
    second_target.parent.mkdir(parents=True)
    first_target.write_text("one", encoding="utf-8")
    second_target.write_text("two", encoding="utf-8")
    first_uri = path_to_run_uri(first_run)
    second_uri = path_to_run_uri(second_run)
    stores = (
        CollectionStore(
            first_uri,
            (
                _candidate(
                    "candidate-1",
                    first_target,
                    detail={"ownership_key": "run-one"},
                ),
            ),
        ),
        CollectionStore(
            second_uri,
            (
                _candidate(
                    "candidate-2",
                    second_target,
                    detail={"ownership_key": "run-two"},
                ),
            ),
        ),
    )

    report = plan_collection_gc(
        (
            CollectionCleanupTarget(
                run_uri=first_uri,
                store=cast(PerRunAuthorityStore, stores[0]),
                managed_roots=(_managed_root(first_run, "run-one"),),
            ),
            CollectionCleanupTarget(
                run_uri=second_uri,
                store=cast(PerRunAuthorityStore, stores[1]),
                managed_roots=(_managed_root(second_run, "run-two"),),
            ),
        ),
        collection_id="collection-1",
        created_at="2020-01-01T00:00:00Z",
        report_id_prefix="collection",
    )

    assert report.summary == {
        "runs": 2,
        "candidates": 2,
        "selected": 2,
        "skipped": 0,
        "rejected": 0,
        "dry_run": True,
    }
    assert [run_report.report_id for run_report in report.reports] == [
        "collection-cleanup-report-1",
        "collection-cleanup-report-2",
    ]
    assert stores[0].append_report_calls == 0
    assert stores[1].append_report_calls == 0


def test_execute_collection_gc_deletes_candidates_without_deleting_runs(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs" / "one"
    target = run_root / "tmp" / "payload.txt"
    target.parent.mkdir(parents=True)
    target.write_text("payload", encoding="utf-8")
    run_uri = path_to_run_uri(run_root)
    store = CollectionStore(
        run_uri,
        (
            _candidate(
                "candidate-1",
                target,
                detail={"ownership_key": "run-one"},
            ),
        ),
    )
    cleanup_target = CollectionCleanupTarget(
        run_uri=run_uri,
        store=cast(PerRunAuthorityStore, store),
        managed_roots=(_managed_root(run_root, "run-one"),),
    )
    report = plan_collection_gc(
        (cleanup_target,),
        collection_id="collection-1",
        created_at="2020-01-01T00:00:00Z",
    )

    result = execute_collection_gc(
        (cleanup_target,),
        report,
        _intent(),
        result_id="collection-result-1",
        created_at="2020-01-01T00:00:05Z",
        result_id_prefix="collection",
        emit_event=False,
    )

    assert not target.exists()
    assert run_root.exists()
    assert result.summary == {
        "runs": 1,
        "candidates": 1,
        "deleted": 1,
        "skipped": 0,
        "rejected": 0,
        "failed": 0,
    }
    assert result.results[0].result.entries[0].outcome is CleanupResultOutcome.DELETED
    assert store.results[0] == result.results[0]


def test_collection_gc_rejects_duplicate_run_targets() -> None:
    store = CollectionStore("file:///runs/one", ())
    target = CollectionCleanupTarget(
        run_uri="file:///runs/one",
        store=cast(PerRunAuthorityStore, store),
    )

    with pytest.raises(CleanupError, match="unique run_uri"):
        plan_collection_gc((target, target))


def _candidate(
    candidate_id: str,
    target: Path,
    *,
    detail: dict[str, PlainData] | None = None,
) -> CleanupCandidate:
    return CleanupCandidate(
        candidate_id=candidate_id,
        kind=CleanupCandidateKind.STAGED_PAYLOAD,
        uri=path_to_run_uri(target),
        reason=LifecycleReason(
            code="temporary_payload",
            detail={} if detail is None else detail,
        ),
        recorded_at="2020-01-01T00:00:00Z",
        revision=BackendRevision(sequence=1, token="rev-1"),
    )


def _managed_root(path: Path, ownership_key: str) -> CleanupManagedRoot:
    return CleanupManagedRoot(
        root_id=f"{ownership_key}-root",
        uri=path_to_run_uri(path),
        ownership_key=ownership_key,
    )


def _intent() -> CleanupDeleteIntent:
    return CleanupDeleteIntent(
        intent_id="intent-1",
        requested_by="tester",
        requested_at="2020-01-01T00:00:04Z",
        reason="unit test cleanup",
    )
