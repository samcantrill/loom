"""Integration coverage for collection cleanup over persisted authority facts."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from loom.authority._repository import (
    AuthorityRepository,
    initialize_authority_repository,
)
from loom.pipeline.cleanup import (
    CleanupDeleteIntent,
    CleanupManagedRoot,
    CleanupResultOutcome,
    CollectionCleanupTarget,
    execute_collection_gc,
    plan_collection_gc,
)
from loom.pipeline.stores import (
    CleanupCandidateKind,
    LifecycleReason,
    PerRunAuthorityStore,
    path_to_run_uri,
)


pytestmark = pytest.mark.integration


def test_collection_gc_uses_per_run_authority_and_keeps_run_directories(
    tmp_path: Path,
) -> None:
    repository = initialize_authority_repository(
        tmp_path / "authority",
        service_generation="generation-1",
    )
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
    repository.admit_run(first_uri)
    repository.admit_run(second_uri)
    repository.record_cleanup_candidate(
        first_uri,
        candidate_id="candidate-one",
        kind=CleanupCandidateKind.STAGED_PAYLOAD,
        uri=path_to_run_uri(first_target),
        reason=LifecycleReason(
            code="temporary_payload",
            detail={"ownership_key": "run-one"},
        ),
    )
    repository.record_cleanup_candidate(
        second_uri,
        candidate_id="candidate-two",
        kind=CleanupCandidateKind.STAGED_PAYLOAD,
        uri=path_to_run_uri(second_target),
        reason=LifecycleReason(
            code="temporary_payload",
            detail={"ownership_key": "run-two"},
        ),
    )
    targets = (
        CollectionCleanupTarget(
            run_uri=first_uri,
            store=cast(PerRunAuthorityStore, repository),
            managed_roots=(
                CleanupManagedRoot(
                    root_id="run-one-root",
                    uri=path_to_run_uri(first_run),
                    ownership_key="run-one",
                ),
            ),
        ),
        CollectionCleanupTarget(
            run_uri=second_uri,
            store=cast(PerRunAuthorityStore, repository),
            managed_roots=(
                CleanupManagedRoot(
                    root_id="run-two-root",
                    uri=path_to_run_uri(second_run),
                    ownership_key="run-two",
                ),
            ),
        ),
    )

    report = plan_collection_gc(
        targets,
        collection_id="collection-1",
        created_at="2020-01-01T00:00:00Z",
    )
    result = execute_collection_gc(
        targets,
        report,
        CleanupDeleteIntent(
            intent_id="intent-1",
            requested_by="tester",
            requested_at="2020-01-01T00:00:04Z",
            reason="integration collection cleanup",
        ),
        result_id="collection-result-1",
        created_at="2020-01-01T00:00:05Z",
        emit_event=False,
    )

    assert report.summary["selected"] == 2
    assert result.summary["deleted"] == 2
    assert not first_target.exists()
    assert not second_target.exists()
    assert first_run.exists()
    assert second_run.exists()
    assert {fact.result.entries[0].outcome for fact in result.results} == {
        CleanupResultOutcome.DELETED
    }
    reopened = AuthorityRepository(tmp_path / "authority")
    assert reopened.list_cleanup_results(first_uri) == (result.results[0],)
    assert reopened.list_cleanup_results(second_uri) == (result.results[1],)
