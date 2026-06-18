"""Contract tests for deferred result reconciliation."""

from __future__ import annotations

import pytest

from loom.pipeline.status import StageStatus
from loom.pipeline.stores import (
    DeferredReconciliationCode,
    reconcile_deferred_result,
)
from tests.support.deferred_finalization import ready_deferred_authority

pytestmark = pytest.mark.contract


def test_deferred_reconciliation_commits_success_through_authority() -> None:
    authority, envelope, lease = ready_deferred_authority()

    result = reconcile_deferred_result(
        authority,
        envelope,
        fencing_token=lease.fencing_token,
    )

    assert result.accepted
    assert result.code is DeferredReconciliationCode.ACCEPTED
    snapshot = authority.snapshot(envelope.run_uri)
    stage = snapshot.stages[0]
    assert stage.status is StageStatus.SUCCEEDED
    assert stage.latest_commit is not None
    assert tuple(fact.artifact_name for fact in stage.artifact_facts) == ("out",)


def test_deferred_reconciliation_rejects_superseded_envelope() -> None:
    authority, envelope, lease = ready_deferred_authority()
    first = reconcile_deferred_result(
        authority,
        envelope,
        fencing_token=lease.fencing_token,
    )

    second = reconcile_deferred_result(
        authority,
        envelope,
        fencing_token=lease.fencing_token,
    )

    assert first.accepted
    assert not second.accepted
    assert second.code is DeferredReconciliationCode.SUPERSEDED_STAGE
