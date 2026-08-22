from dataclasses import dataclass

from loom.pipeline.planning import (
    FingerprintStatus,
    PlanAction,
    RetryAuthorization,
    StagePlan,
    evaluate_attempt_readiness,
)
from loom.pipeline.status import StageStatus


@dataclass(frozen=True)
class _Attempt:
    attempt: int
    attempt_id: str
    status: StageStatus


def _plan(action: PlanAction = PlanAction.RUN) -> StagePlan:
    return StagePlan(
        stage_name="consume",
        action=action,
        base_action=action,
        fingerprint_status=FingerprintStatus.PENDING_INPUTS,
        fingerprint=None,
        resume_check=None,
        reasons=(),
        bound_inputs={},
        pending_inputs=(),
        reusable_outputs={},
        declared_outputs={},
        upstream_stages=("produce",),
        downstream_stages=(),
        selected_by=(),
        invalidated_by=(),
    )


def test_run_requires_success_or_exact_upstream_commit() -> None:
    plan = _plan()
    assert (
        evaluate_attempt_readiness(
            plan, completed_stages={"produce"}, successful_stages=()
        )
        is None
    )
    ready = evaluate_attempt_readiness(
        plan,
        completed_stages={"produce"},
        successful_stages=(),
        committed_outputs={"produce": "commit-1"},
    )
    assert ready is not None
    assert ready.upstream_commits == {"produce": "commit-1"}


def test_controller_action_waits_for_terminal_upstream_but_not_capacity() -> None:
    ready = evaluate_attempt_readiness(
        _plan(PlanAction.BLOCKED),
        completed_stages={"produce"},
        successful_stages=(),
    )
    assert ready is not None
    assert ready.action is PlanAction.BLOCKED


def test_cancellation_and_active_attempt_fail_closed() -> None:
    assert (
        evaluate_attempt_readiness(
            _plan(), completed_stages={"produce"}, run_cancelled=True
        )
        is None
    )
    assert (
        evaluate_attempt_readiness(
            _plan(),
            completed_stages={"produce"},
            current_attempt=_Attempt(1, "consume-1", StageStatus.RUNNING),
        )
        is None
    )


def test_failed_attempt_requires_exact_retry_authorization() -> None:
    attempt = _Attempt(1, "consume-1", StageStatus.FAILED)
    assert (
        evaluate_attempt_readiness(
            _plan(), completed_stages={"produce"}, current_attempt=attempt
        )
        is None
    )
    ready = evaluate_attempt_readiness(
        _plan(),
        completed_stages={"produce"},
        current_attempt=attempt,
        retry_authorization=RetryAuthorization("retry-1", 2),
    )
    assert ready is not None
    assert ready.next_attempt == 2
    assert ready.retry_decision_id == "retry-1"


def test_pending_attempt_is_ready_only_as_exact_prepared_replay() -> None:
    attempt = _Attempt(1, "consume-1", StageStatus.PENDING)
    assert (
        evaluate_attempt_readiness(
            _plan(), completed_stages={"produce"}, current_attempt=attempt
        )
        is None
    )
    replay = evaluate_attempt_readiness(
        _plan(),
        completed_stages={"produce"},
        current_attempt=attempt,
        prepared_generation="generation-1",
    )
    assert replay is not None
    assert replay.readiness_generation == "generation-1"
    assert replay.next_attempt == 1
