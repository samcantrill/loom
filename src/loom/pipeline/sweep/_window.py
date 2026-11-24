"""Admission windows for waiting sweep invocations, owned by the existing manifest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4
from typing import TYPE_CHECKING, Any, cast

from loom.serialization import thaw_plain_data

from .dispatch import (
    _accepted,
    _observed_owner,
    _occupies_slot,
    _record_failure,
    _record_observation,
    _reserve_trial,
    _retain_trial,
    _terminal,
    _update_state,
)
from .errors import SweepProtocolError
from .manifest import SWEEP_MANIFEST_FILE_NAME, read_sweep_manifest

if TYPE_CHECKING:
    from loom.coordinator import RunObservation, RunRequest
    from loom.deployment import AvailableDeployment
    from .runner import SweepPlan


@dataclass
class _Trial:
    trial_id: str
    request: RunRequest
    available: AvailableDeployment
    last: dict[str, Any]


def _close(available: AvailableDeployment, deadline: float | None) -> None:
    from loom.queue.errors import QueueError

    try:
        available.release(deadline)
    except QueueError:
        pass
    finally:
        available.client.close()


def run_waiting_window(
    plan: SweepPlan,
    template: RunRequest,
    deployment: str | Path,
    root: Path,
    limit: int,
    timeout: float | None,
) -> None:
    from loom._run import (
        _cleanup_step,
        _role_outcome,
        _run_outcome,
        _start_exact,
        _validate_run_arguments,
        _validate_run_selection,
    )
    from loom.coordinator import CoordinatorClientError
    from loom.deployment import ensure_available, load_deployment
    from loom.queue.errors import QueueError

    _validate_run_arguments(template, wait=True, timeout_seconds=timeout)
    selection = load_deployment(deployment)
    _validate_run_selection(template, selection)
    deadline = monotonic() + timeout if timeout is not None else None
    observing = False
    tried: set[str] = set()
    active: dict[str, _Trial] = {}
    cleaning: dict[str, tuple[_Trial, RunObservation, float]] = {}
    trials = {trial.trial_id: trial for trial in plan.trials}
    records = read_sweep_manifest(root / SWEEP_MANIFEST_FILE_NAME).metadata.get(
        "native_runs", {}
    )
    # Validate even completed rows on resume; a changed template must never be
    # silently combined with already selected trials.
    for trial_id, record in cast(dict[str, Any], thaw_plain_data(records)).items():
        _retain_trial({trial_id: record}, trials[trial_id], template, deployment)

    def reserve(runs):
        outstanding = {key for key, row in runs.items() if _occupies_slot(row)}
        # A recorded explicit retry may have advanced the previously terminal admission.
        existing = (
            key
            for key in runs
            if key not in tried
            and (
                key in outstanding
                or runs[key].get("retry_request")
                or (
                    _terminal(runs[key].get("observation") or {})
                    and "cleanup" not in runs[key]
                )
            )
        )
        trial_id = next(existing, None)
        if trial_id is None and len(outstanding) < limit:
            trial_id = next(
                (
                    key
                    for key in trials
                    if key not in tried
                    and (key not in runs or runs[key].get("dispatch_failed"))
                ),
                None,
            )
        if trial_id is None:
            return None
        request = _reserve_trial(runs, trials[trial_id], template, deployment)
        return trial_id, request, runs[trial_id]

    def expired():
        return deadline is not None and monotonic() >= deadline

    def open_trial(trial_id, request, record):
        owner = _observed_owner(record)
        startup_end = monotonic() + selection.startup_seconds
        if deadline is not None:
            startup_end = min(deadline, startup_end)
        attachment = (
            ("observe-" + uuid4().hex)
            if _accepted(record)
            else request.preparation.operation_id
        )
        available = ensure_available(
            selection,
            attachment_id=attachment,
            deadline=startup_end,
            expected_coordinator_id=owner,
        )
        last = record.get("observation") or {}
        try:

            def bind(runs):
                current = _observed_owner(runs[trial_id])
                if current is not None and current != available.connection_id:
                    raise SweepProtocolError(
                        "native trial coordinator conflicts with retained owner"
                    )
                runs[trial_id]["coordinator_id"] = available.connection_id

            _update_state(root, bind)
            if not _accepted(record):
                observed = _start_exact(
                    available,
                    request,
                    deadline=startup_end,
                    expected_coordinator_id=available.connection_id,
                )
                outcome = _run_outcome(
                    available, observed, wait=False, deadline=deadline
                )
                last = observed.to_dict()
                _update_state(
                    root,
                    lambda runs: _record_observation(
                        runs[trial_id], last, outcome.cleanup
                    ),
                )
            active[trial_id] = _Trial(trial_id, request, available, last)
        except BaseException:
            _close(available, deadline)
            raise

    def advance(trial: _Trial) -> tuple[bool, bool]:
        # A single passive pass per owner. The lower-level iterator also lets
        # Ctrl-C escape to the invocation rather than consuming it as a run wait.
        observed: RunObservation | None = None
        for observed in trial.available.client._run_observation_steps(
            trial.request.preparation.operation_id,
            trial.available.description,
            deadline=deadline,
        ):
            pass
        assert observed is not None
        row = cast(dict[str, Any], observed.to_dict())
        terminal = _terminal(row)
        blocked = (row.get("admission") or {}).get("state") == "BLOCKED"
        if row != trial.last:
            _update_state(
                root, lambda runs: _record_observation(runs[trial.trial_id], row)
            )
            trial.last = row
        if terminal or blocked:
            # Release the same startup attachment that protected this send.
            # Other accepted operations and their attachments protect their own roles.
            try:
                trial.available.release(deadline)
            except QueueError:
                pass
            if terminal:
                cleanup_end = monotonic() + selection.startup_seconds
                cleaning[trial.trial_id] = (
                    trial,
                    observed,
                    min(cleanup_end, deadline) if deadline is not None else cleanup_end,
                )
            else:
                outcome = _run_outcome(
                    trial.available, observed, wait=False, deadline=deadline
                )
                _update_state(
                    root,
                    lambda runs: _record_observation(
                        runs[trial.trial_id], row, outcome.cleanup
                    ),
                )
                trial.available.client.close()
            del active[trial.trial_id]
        return terminal, blocked

    try:
        while not expired():
            while len(active) < limit and not expired():
                reservation = _update_state(root, reserve, skip_none=True)
                if reservation is None:
                    break
                trial_id, request, record = reservation
                tried.add(trial_id)
                try:
                    open_trial(trial_id, request, record)
                except (OSError, QueueError) as error:
                    _update_state(
                        root,
                        lambda runs, exc=error: _record_failure(runs[trial_id], exc),
                    )
            if active and not observing:
                observing = True
                if selection.wait_seconds is not None:
                    watch_end = monotonic() + selection.wait_seconds
                    deadline = (
                        min(deadline, watch_end) if deadline is not None else watch_end
                    )
            if not (active or cleaning) or expired():
                return
            completed = False
            for trial in tuple(active.values()):
                try:
                    terminal, blocked = advance(trial)
                except CoordinatorClientError as exc:
                    if exc.code not in {"unavailable", "deadline_exceeded"}:
                        raise
                    if expired():
                        return
                    # A run-owned service may retire between the last physical
                    # release and our final read. Reopen only the bound owner.
                    previous = trial.available
                    _close(previous, deadline)
                    try:
                        trial.available = ensure_available(
                            selection,
                            attachment_id="observe-" + uuid4().hex,
                            expected_coordinator_id=previous.connection_id,
                            deadline=deadline,
                        )
                    except CoordinatorClientError as reopen_error:
                        if reopen_error.code in {"unavailable", "deadline_exceeded"}:
                            return
                        raise
                    continue
                if blocked or expired():
                    return
                completed |= terminal
            # A newly free slot goes to the next trial before terminal cleanup.
            if completed:
                continue
            for trial_id, (finished, observed, end) in tuple(cleaning.items()):
                cleanup = _cleanup_step(finished.available, observed, end)
                if cleanup is not None:
                    outcome = _role_outcome(finished.available, observed, cleanup)
                    _update_state(
                        root,
                        lambda runs: _record_observation(
                            runs[trial_id], finished.last, outcome.cleanup
                        ),
                    )
                    finished.available.client.close()
                    del cleaning[trial_id]
            if active or cleaning:
                sleep(
                    0.1
                    if deadline is None
                    else min(0.1, max(0, deadline - monotonic()))
                )
    finally:
        for trial in active.values():
            _close(trial.available, deadline)
        for finished, _, _ in cleaning.values():
            finished.available.client.close()
