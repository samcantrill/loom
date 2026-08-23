"""Expected-state contract shared by managed execution authority adapters."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from loom.pipeline.status import StageStatus
from loom.pipeline.stores import PreparedAttemptRequest, path_to_run_uri
from loom.pipeline.stores.authority import AuthorityStoreError
from loom.pipeline.stores.read_models import LifecycleReason
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from tests.support.authority_stores import InMemoryPerRunAuthorityStore


pytestmark = pytest.mark.contract


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_managed_authority_fence_is_replayable_and_rejects_stale_results(
    tmp_path: Path, backend: str
) -> None:
    store = (
        InMemoryPerRunAuthorityStore()
        if backend == "memory"
        else SQLitePerRunAuthorityStore()
    )
    run_uri = path_to_run_uri(tmp_path / backend / "run")
    revision = store.create_run(run_uri)
    prepared = store.ensure_prepared_attempt(
        run_uri,
        PreparedAttemptRequest(
            operation_id="prepare-1",
            request_digest="digest-1",
            admission_id="admission-1",
            stage_name="build",
            readiness_generation="ready-1",
            expected_revision=revision,
            expected_stage_status=None,
            expected_attempt_id=None,
            next_attempt=1,
            owner_id="coordinator",
            plan_fingerprint="plan-1",
            bound_inputs={},
            upstream_commits={},
        ),
    )
    attempt_id = prepared.attempt.attempt_id
    store.bind_prepared_attempt(
        run_uri, assignment_id="assignment-1", attempt_id=attempt_id
    )
    fence = store.grant_prepared_attempt(
        run_uri, assignment_id="assignment-1", attempt_id=attempt_id
    )
    assert (
        store.grant_prepared_attempt(
            run_uri, assignment_id="assignment-1", attempt_id=attempt_id
        )
        == fence
    )
    reason = LifecycleReason(code="managed_worker_failed", message="failed")
    terminal = store.record_managed_attempt_terminal(
        run_uri,
        fence=fence,
        status=StageStatus.FAILED,
        reason=reason,
    )
    replay = store.record_managed_attempt_terminal(
        run_uri,
        fence=fence,
        status=StageStatus.FAILED,
        reason=reason,
    )

    assert replay.revision == terminal.revision
    store.bind_prepared_attempt(
        run_uri, assignment_id="assignment-1", attempt_id=attempt_id
    )
    assert (
        store.grant_prepared_attempt(
            run_uri, assignment_id="assignment-1", attempt_id=attempt_id
        )
        == fence
    )
    store.confirm_execution_started(run_uri, fence=fence)
    with pytest.raises((AuthorityStoreError, ValueError), match="stale"):
        store.record_managed_attempt_terminal(
            run_uri,
            fence=replace(fence, fencing_token="stale"),
            status=StageStatus.FAILED,
            reason=reason,
        )


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_managed_authority_unbind_retains_an_exact_replay_tombstone(
    tmp_path: Path, backend: str
) -> None:
    store = (
        InMemoryPerRunAuthorityStore()
        if backend == "memory"
        else SQLitePerRunAuthorityStore()
    )
    run_uri = path_to_run_uri(tmp_path / backend / "declined")
    revision = store.create_run(run_uri)
    prepared = store.ensure_prepared_attempt(
        run_uri,
        PreparedAttemptRequest(
            operation_id="prepare-decline",
            request_digest="digest-decline",
            admission_id="admission-1",
            stage_name="build",
            readiness_generation="ready-1",
            expected_revision=revision,
            expected_stage_status=None,
            expected_attempt_id=None,
            next_attempt=1,
            owner_id="coordinator",
            plan_fingerprint="plan-1",
            bound_inputs={},
            upstream_commits={},
        ),
    )
    attempt_id = prepared.attempt.attempt_id
    store.bind_prepared_attempt(
        run_uri, assignment_id="assignment-declined", attempt_id=attempt_id
    )

    store.unbind_prepared_attempt(
        run_uri, assignment_id="assignment-declined", attempt_id=attempt_id
    )
    store.unbind_prepared_attempt(
        run_uri, assignment_id="assignment-declined", attempt_id=attempt_id
    )
    store.bind_prepared_attempt(
        run_uri, assignment_id="assignment-declined", attempt_id=attempt_id
    )
    with pytest.raises((AuthorityStoreError, ValueError), match="conflicts"):
        store.bind_prepared_attempt(
            run_uri,
            assignment_id="assignment-declined",
            attempt_id=f"{attempt_id}-different",
        )
    with pytest.raises((AuthorityStoreError, ValueError), match="conflicts"):
        store.unbind_prepared_attempt(
            run_uri,
            assignment_id="assignment-declined",
            attempt_id=f"{attempt_id}-different",
        )
    with pytest.raises((AuthorityStoreError, ValueError), match="not bound"):
        store.grant_prepared_attempt(
            run_uri, assignment_id="assignment-declined", attempt_id=attempt_id
        )

    store.bind_prepared_attempt(
        run_uri, assignment_id="assignment-replacement", attempt_id=attempt_id
    )
