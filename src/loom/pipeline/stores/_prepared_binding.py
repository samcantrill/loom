"""Prepared binding arbitration shared by the two SQLite authority owners."""

from __future__ import annotations

from enum import Enum, auto
import json
import sqlite3

from loom.pipeline.status import StageStatus
from loom.serialization import stable_json_bytes

from .authority import ExecutionFence, PreparedBindingObservation, PreparedBindingState
from .read_models import LifecycleReason


class Settlement(Enum):
    ACCEPT_REPLAY = auto()
    DECLINE = auto()
    UNBIND = auto()
    FAIL = auto()


def observe_binding(
    row: sqlite3.Row,
    assignment_id: str,
    attempt_id: str,
    *,
    error: type[Exception],
    settling: bool = False,
) -> PreparedBindingObservation:
    """Interpret one consistent read of the assignment, tombstone and attempt."""
    state = PreparedBindingState.ABSENT
    reason = None
    fence = None
    if row["receipt_attempt"] not in (None, attempt_id):
        if settling:
            raise error("assignment unbind conflicts")
        raise error("assignment binding conflicts with the attempt already recorded")
    if row["bound_attempt"] not in (None, attempt_id):
        if settling:
            raise error("only the same ungranted binding may unbind")
        raise error("assignment binding conflicts with the attempt already recorded")
    if row["bound_attempt"] is not None:
        if row["binding_state"] == "bound":
            state = PreparedBindingState.BOUND
        elif (
            row["binding_state"] in {"granted", "running", "terminal"}
            and row["fence"] is not None
        ):
            state = PreparedBindingState.GRANTED
            fence = ExecutionFence(assignment_id, attempt_id, row["fence"])
        elif (
            row["binding_state"] == "terminal"
            and row["attempt_status"] == StageStatus.FAILED.value
        ):
            state = PreparedBindingState.FAILED
            reason = LifecycleReason.from_dict(json.loads(row["reason_json"]))
        else:
            raise error("prepared binding state conflicts with its execution fence")
    elif row["receipt_attempt"] is not None:
        state = PreparedBindingState.UNBOUND
        if (
            row["owner"] is None
            and row["attempt_status"] == StageStatus.FAILED.value
            and row["reason_json"] is not None
        ):
            # Older authorities deleted a failed binding and left an ordinary
            # unbind receipt. Slurm's retained accounting reason names the owner.
            recorded = LifecycleReason.from_dict(json.loads(row["reason_json"]))
            old_owner = recorded.detail.get("assignment_id")
            if old_owner is None and recorded.code != "action.producer_abandoned":
                if row["other_receipt"]:
                    raise error(
                        "legacy pre-start failure has ambiguous assignment receipts"
                    )
                old_owner = assignment_id
            if old_owner == assignment_id:
                state, reason = PreparedBindingState.FAILED, recorded
    return PreparedBindingObservation(assignment_id, attempt_id, state, fence, reason)


def decide_settlement(
    row: sqlite3.Row,
    assignment_id: str,
    attempt_id: str,
    reason: LifecycleReason | None,
    *,
    prepared_without_owner: bool,
    cancelled: bool,
    error: type[Exception],
) -> Settlement:
    """Choose the single effect to apply in the transaction that read the facts."""
    if reason is None and row["receipt_attempt"] == attempt_id:
        return Settlement.ACCEPT_REPLAY
    observation = observe_binding(
        row, assignment_id, attempt_id, error=error, settling=True
    )
    if observation.state in {PreparedBindingState.FAILED, PreparedBindingState.UNBOUND}:
        if reason is None or (
            observation.reason is not None
            and stable_json_bytes(observation.reason.to_dict())
            == stable_json_bytes(reason.to_dict())
        ):
            return Settlement.ACCEPT_REPLAY
        return Settlement.DECLINE
    if observation.state is not PreparedBindingState.BOUND:
        if reason is not None:
            return Settlement.DECLINE
        # A cancellation may cover a prepared reservation whose bind never ran.
        if (
            observation.state is PreparedBindingState.ABSENT
            and prepared_without_owner
            and cancelled
        ):
            return Settlement.UNBIND
        raise error("only the same ungranted binding may unbind")
    if reason is None:
        return Settlement.UNBIND
    if cancelled:
        raise error("run cancellation epoch is effective")
    if row["attempt_status"] != StageStatus.PENDING.value:
        raise error("unstarted failure requires the bound pending attempt")
    return Settlement.FAIL
