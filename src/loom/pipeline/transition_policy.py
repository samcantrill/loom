"""The single lifecycle transition policy shared by authority backends."""

from __future__ import annotations

from enum import StrEnum

from .status import RunStatus, StageStatus


class TransitionIntent(StrEnum):
    """Why a lifecycle transition is being requested."""

    NORMAL = "normal"
    RESUME = "resume"
    RECOVERY = "recovery"


class InvalidRunTransition(ValueError):
    """Raised when a requested run transition is not meaningful."""


class InvalidStageTransition(ValueError):
    """Raised when a requested stage transition is not meaningful."""


_RUN_NORMAL = frozenset({
    (RunStatus.CREATED, RunStatus.PLANNED),
    # Kept for the established public direct-execution contract.
    (RunStatus.CREATED, RunStatus.RUNNING),
    (RunStatus.CREATED, RunStatus.SUBMITTED),
    (RunStatus.CREATED, RunStatus.FAILED),
    (RunStatus.CREATED, RunStatus.CANCELLED),
    (RunStatus.PLANNED, RunStatus.RUNNING),
    (RunStatus.PLANNED, RunStatus.SUBMITTED),
    (RunStatus.PLANNED, RunStatus.FAILED),
    (RunStatus.PLANNED, RunStatus.CANCELLED),
    (RunStatus.RUNNING, RunStatus.SUBMITTED),
    (RunStatus.RUNNING, RunStatus.SUCCEEDED),
    (RunStatus.RUNNING, RunStatus.FAILED),
    (RunStatus.RUNNING, RunStatus.CANCELLED),
    (RunStatus.RUNNING, RunStatus.INTERRUPTED),
    (RunStatus.SUBMITTED, RunStatus.RUNNING),
    (RunStatus.SUBMITTED, RunStatus.SUCCEEDED),
    (RunStatus.SUBMITTED, RunStatus.FAILED),
    (RunStatus.SUBMITTED, RunStatus.CANCELLED),
    (RunStatus.SUBMITTED, RunStatus.INTERRUPTED),
})
_RUN_RESUME = frozenset(
    (previous, target)
    for previous in (
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.INTERRUPTED,
        RunStatus.SUCCEEDED,
    )
    for target in (RunStatus.PLANNED, RunStatus.RUNNING, RunStatus.SUBMITTED)
)
_RUN_RECOVERY = frozenset({
    (RunStatus.RUNNING, RunStatus.INTERRUPTED),
    (RunStatus.SUBMITTED, RunStatus.INTERRUPTED),
    (RunStatus.RUNNING, RunStatus.FAILED),
    (RunStatus.SUBMITTED, RunStatus.FAILED),
})

_STAGE_NORMAL = frozenset({
    (None, StageStatus.PENDING),
    (None, StageStatus.RUNNING),
    (None, StageStatus.SUBMITTED),
    (None, StageStatus.FAILED),
    (None, StageStatus.BLOCKED),
    (None, StageStatus.SKIPPED),
    (None, StageStatus.CANCELLED),
    (StageStatus.PENDING, StageStatus.RUNNING),
    (StageStatus.PENDING, StageStatus.SUBMITTED),
    (StageStatus.PENDING, StageStatus.SUCCEEDED),
    (StageStatus.PENDING, StageStatus.FAILED),
    (StageStatus.PENDING, StageStatus.BLOCKED),
    (StageStatus.PENDING, StageStatus.SKIPPED),
    (StageStatus.PENDING, StageStatus.CANCELLED),
    (StageStatus.RUNNING, StageStatus.SUBMITTED),
    # Attempt allocation precedes durable worker preparation in existing stores.
    (StageStatus.RUNNING, StageStatus.PENDING),
    (StageStatus.RUNNING, StageStatus.SUCCEEDED),
    (StageStatus.RUNNING, StageStatus.FAILED),
    (StageStatus.RUNNING, StageStatus.BLOCKED),
    (StageStatus.RUNNING, StageStatus.CANCELLED),
    (StageStatus.SUBMITTED, StageStatus.RUNNING),
    (StageStatus.SUBMITTED, StageStatus.SUCCEEDED),
    (StageStatus.SUBMITTED, StageStatus.FAILED),
    (StageStatus.SUBMITTED, StageStatus.BLOCKED),
    (StageStatus.SUBMITTED, StageStatus.CANCELLED),
})
_STAGE_RESUME = frozenset(
    (previous, target)
    for previous in (
        StageStatus.SUCCEEDED,
        StageStatus.FAILED,
        StageStatus.BLOCKED,
        StageStatus.SKIPPED,
        StageStatus.STALE,
        StageStatus.CANCELLED,
    )
    for target in (
        StageStatus.PENDING,
        StageStatus.RUNNING,
        StageStatus.SUBMITTED,
        StageStatus.SUCCEEDED,
        StageStatus.FAILED,
        StageStatus.BLOCKED,
        StageStatus.SKIPPED,
        StageStatus.STALE,
        StageStatus.CANCELLED,
    )
)
_STAGE_RECOVERY = frozenset({
    (StageStatus.RUNNING, StageStatus.PENDING),
    (StageStatus.SUBMITTED, StageStatus.PENDING),
    (StageStatus.RUNNING, StageStatus.STALE),
    (StageStatus.SUBMITTED, StageStatus.STALE),
})


def ensure_run_transition(
    previous: RunStatus,
    target: RunStatus,
    *,
    intent: TransitionIntent = TransitionIntent.NORMAL,
) -> None:
    allowed = {
        TransitionIntent.NORMAL: _RUN_NORMAL,
        TransitionIntent.RESUME: _RUN_RESUME,
        TransitionIntent.RECOVERY: _RUN_RECOVERY,
    }[TransitionIntent(intent)]
    if (RunStatus(previous), RunStatus(target)) not in allowed:
        raise InvalidRunTransition(
            f"{previous.value} cannot become {target.value} "
            f"for {TransitionIntent(intent).value}"
        )


def ensure_stage_transition(
    previous: StageStatus | None,
    target: StageStatus,
    *,
    intent: TransitionIntent = TransitionIntent.NORMAL,
) -> None:
    allowed = {
        TransitionIntent.NORMAL: _STAGE_NORMAL,
        TransitionIntent.RESUME: _STAGE_RESUME,
        TransitionIntent.RECOVERY: _STAGE_RECOVERY,
    }[TransitionIntent(intent)]
    normalized = None if previous is None else StageStatus(previous)
    if (normalized, StageStatus(target)) not in allowed:
        previous_value = "<missing>" if normalized is None else normalized.value
        raise InvalidStageTransition(
            f"{previous_value} cannot become {target.value} "
            f"for {TransitionIntent(intent).value}"
        )


__all__ = [
    "TransitionIntent",
    "InvalidRunTransition",
    "InvalidStageTransition",
    "ensure_run_transition",
    "ensure_stage_transition",
]
