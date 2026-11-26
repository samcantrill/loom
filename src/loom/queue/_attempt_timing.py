"""Process-local diagnostics for execution of an exact managed attempt."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING

from loom.serialization import PlainData

from ._phase_timing import PhaseTimings, log_phases, milestone

if TYPE_CHECKING:
    from ._managed_local import ManagedAssignment
    from ._remote_stage_execution import _ResidentAssignmentBundle
    from .slurm_ready_stage import SlurmStageDelivery


def assignment_milestone(
    action: str,
    assignment: ManagedAssignment | _ResidentAssignmentBundle | SlurmStageDelivery,
    *,
    collector: PhaseTimings | None = None,
) -> None:
    milestone(
        action, collector=collector, assignment_id=assignment.assignment_id,
        stage_work_id=assignment.stage_work_id, stage_name=assignment.stage_name,
        attempt_id=assignment.attempt_id, attempt=assignment.attempt,
    )


@contextmanager
def stage_invocation(
    assignment: _ResidentAssignmentBundle | SlurmStageDelivery, timings: PhaseTimings,
) -> Iterator[None]:
    """Retain guest-clock observations of project code in the native worker result."""
    assignment_milestone("stage_run_entered", assignment, collector=timings)
    try:
        yield
    except BaseException:
        assignment_milestone("stage_run_raised", assignment, collector=timings)
        raise
    else:
        assignment_milestone("stage_run_returned", assignment, collector=timings)


def report_worker_invocation(metadata: Mapping[str, PlainData], assignment_id: str) -> None:
    """Relay the guest timestamps when a supervised worker's stderr was detached."""
    native = metadata.get("native_timings")
    if not isinstance(native, Mapping):
        return
    spans = native.get("spans")
    if not isinstance(spans, (list, tuple)):
        return
    try:
        observed: list[PlainData] = []
        for span in spans[:64]:
            if not isinstance(span, Mapping):
                continue
            action, started, attrs = (span.get(key) for key in ("action", "started_at", "attributes"))
            if (action not in ("stage_run_entered", "stage_run_returned", "stage_run_raised")
                or not isinstance(started, str) or len(started) > 64
                or not isinstance(attrs, Mapping) or attrs.get("assignment_id") != assignment_id):
                continue
            # A returned worker result may come from another package version.
            # Project only bounded clock and identity fields onto the host log.
            facts: dict[str, PlainData] = {}
            for key in ("assignment_id", "stage_work_id", "stage_name", "attempt_id", "host",
                        "attempt", "process_id", "monotonic_ns", "process_origin_ns"):
                value = attrs.get(key)
                if ((isinstance(value, str) and len(value) <= 256)
                    or (type(value) is int and 0 <= value <= 2**63 - 1)):
                    facts[key] = value
            observed.append({"action": action, "started_at": started, "elapsed_nanoseconds": 0,
                             "outcome": "complete", "attributes": facts})
            if len(observed) == 2:
                break
        if observed:
            log_phases({"clock": "process_monotonic", "spans": observed,
                        "operation_id": None, "dropped_spans": 0})
    except Exception:
        pass  # Missing guest telemetry cannot affect result retention.
