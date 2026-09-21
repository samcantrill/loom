"""Only an exact registered producer may continue beyond its graph's epoch."""

import pytest

from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores.authority import (
    ActionProducerBinding,
    CancellationEpochRequest,
    PreparedAttemptRequest,
)
from loom.pipeline.stores.read_models import LifecycleReason
from tests.integration.authority.test_action_result_binding import _consumer

pytestmark = pytest.mark.integration


def _prepare(authority, uri, node):
    return authority.ensure_prepared_attempt(
        uri,
        PreparedAttemptRequest(
            operation_id="prepare-" + node,
            request_digest="digest-" + node,
            admission_id="admit-consumer",
            stage_name=node,
            readiness_generation="ready-" + node,
            expected_revision=authority.open_run(uri).revision,
            expected_stage_status=None,
            expected_attempt_id=None,
            next_attempt=1,
            owner_id="coordinator",
            plan_fingerprint="plan",
            bound_inputs={},
            upstream_commits={},
        ),
    )


@pytest.mark.parametrize("backend", ["embedded", "authenticated"])
@pytest.mark.parametrize("cancel_before_prepare", [True, False])
def test_exact_producer_continues_but_final_detach_revokes_start(
    tmp_path, backend, cancel_before_prepare
):
    uri, authority, _, _ = _consumer(tmp_path, backend)
    binding = ActionProducerBinding("shared-claim", "producer", "producer-1")
    authority.bind_action_producer(uri, binding)
    authority.bind_action_producer(uri, binding)
    cancellation = CancellationEpochRequest(
        operation_id="cancel-original",
        coordinator_id="coordinator",
        run_uri=uri,
        stage_names=("producer", "unrelated"),
    )
    if not cancel_before_prepare:
        _prepare(authority, uri, "producer")
    authority.install_cancellation_epoch(uri, cancellation)
    if cancel_before_prepare:
        _prepare(authority, uri, "producer")
    with pytest.raises(ValueError, match="cancellation epoch"):
        _prepare(authority, uri, "unrelated")
    authority.bind_prepared_attempt(
        uri, assignment_id="assignment", attempt_id=binding.attempt_id
    )
    fence = authority.grant_prepared_attempt(
        uri, assignment_id="assignment", attempt_id=binding.attempt_id
    )
    with pytest.raises(ValueError, match="retained action producer"):
        authority.finalize_cancellation(uri, cancellation)
    authority.release_action_producer(uri, binding)
    authority.release_action_producer(uri, binding)
    with pytest.raises(ValueError, match="settled action producer"):
        authority.bind_action_producer(uri, binding)
    with pytest.raises(ValueError, match="cancellation epoch"):
        authority.confirm_execution_started(uri, fence=fence)
    authority.record_managed_attempt_terminal(
        uri,
        fence=fence,
        status=StageStatus.CANCELLED,
        reason=LifecycleReason(code="worker.contained"),
    )
    assert authority.finalize_cancellation(uri, cancellation).value == "CANCELLED"


@pytest.mark.parametrize("backend", ["embedded", "authenticated"])
def test_failed_run_settles_exact_unstarted_producer_for_retry(tmp_path, backend):
    uri, authority, _, _ = _consumer(tmp_path, backend)
    binding = ActionProducerBinding("abandoned", "producer", "producer-1")
    authority.bind_action_producer(uri, binding)
    _prepare(authority, uri, "producer")
    snapshot = authority.open_run(uri)
    authority.transition_run(
        uri,
        from_status=snapshot.status,
        to_status=RunStatus.FAILED,
        expected_revision=snapshot.revision,
    )
    authority.release_action_producer(uri, binding)
    settled = authority.open_run(uri)
    stage = settled.stages[0]
    assert stage.status is StageStatus.FAILED
    assert stage.attempts[0].status is StageStatus.FAILED
    assert stage.reason is not None and stage.reason.code == "action.producer_abandoned"
    authority.release_action_producer(uri, binding)
    assert authority.open_run(uri) == settled
