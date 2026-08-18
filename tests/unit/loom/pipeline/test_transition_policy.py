"""Lifecycle transition policy regression tests."""

import pytest

from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.transition_policy import (
    InvalidRunTransition,
    InvalidStageTransition,
    TransitionIntent,
    ensure_run_transition,
    ensure_stage_transition,
)


def test_normal_policy_rejects_terminal_rewinds() -> None:
    with pytest.raises(InvalidRunTransition):
        ensure_run_transition(
            RunStatus.SUCCEEDED, RunStatus.RUNNING, intent=TransitionIntent.NORMAL
        )
    with pytest.raises(InvalidStageTransition):
        ensure_stage_transition(
            StageStatus.SUCCEEDED, StageStatus.PENDING, intent=TransitionIntent.NORMAL
        )


def test_resume_policy_allows_explicit_terminal_restarts() -> None:
    ensure_run_transition(
        RunStatus.SUCCEEDED, RunStatus.RUNNING, intent=TransitionIntent.RESUME
    )
    ensure_stage_transition(
        StageStatus.SUCCEEDED, StageStatus.PENDING, intent=TransitionIntent.RESUME
    )
    ensure_stage_transition(
        StageStatus.SUCCEEDED, StageStatus.BLOCKED, intent=TransitionIntent.RESUME
    )


def test_normal_policy_keeps_direct_created_to_running_contract() -> None:
    ensure_run_transition(
        RunStatus.CREATED, RunStatus.RUNNING, intent=TransitionIntent.NORMAL
    )
