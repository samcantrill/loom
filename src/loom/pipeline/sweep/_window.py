"""Admission windows for waiting sweep invocations, owned by the existing manifest."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from threading import Event
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
    attachment_released: bool = False

    def release(self, deadline: float | None) -> None:
        from loom.queue.errors import QueueError

        if not self.attachment_released:
            try:
                self.available.release(deadline)
            except QueueError:
                pass
            self.attachment_released = True


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
    detached = Event()
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

    def read_trial(trial: _Trial) -> RunObservation | None:
        # Each trial's passive read has its own client. Only this worker can
        # replace it if the run-owned service retired after physical release.
        observed = None
        try:
            for observed in trial.available.client._run_observation_steps(
                trial.request.preparation.operation_id, trial.available.description, deadline=deadline,
            ):
                pass
        except CoordinatorClientError as exc:
            if exc.code not in {"unavailable", "deadline_exceeded"} or expired() or detached.is_set():
                raise
            previous = trial.available
            trial.release(deadline)
            trial.available = ensure_available(
                selection, attachment_id="observe-" + uuid4().hex,
                expected_coordinator_id=previous.connection_id, deadline=deadline,
            )
            trial.attachment_released = False
            previous.client.close()
            return None
        assert observed is not None
        return observed

    def cleanup_step(trial: _Trial, observation: RunObservation, end: float):
        trial.release(end)
        return _cleanup_step(trial.available, observation, end)

    def close_after(trial: _Trial, pending: Future | None) -> None:
        # A detached caller can return while the transport is unwinding.
        # The worker that closes the client waits for its physical owner.
        if pending is not None:
            wait((pending,))
        try:
            trial.release(monotonic() + selection.startup_seconds)
        finally:
            trial.available.client.close()

    readers = ThreadPoolExecutor(max_workers=min(limit, 8), thread_name_prefix="sweep-read")
    cleaners = ThreadPoolExecutor(max_workers=min(limit, 2), thread_name_prefix="sweep-cleanup")
    reads: dict[str, Future[RunObservation | None]] = {}
    cleanup_steps: dict[str, Future] = {}
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
            for trial_id, trial in tuple(active.items()):
                if trial_id not in reads:
                    reads[trial_id] = readers.submit(read_trial, trial)
                if not reads[trial_id].done():
                    continue
                future = reads.pop(trial_id)
                try:
                    observed = future.result()
                except CoordinatorClientError as exc:
                    if exc.code not in {"unavailable", "deadline_exceeded"}:
                        raise
                    # Keep the uncertain slot in the manifest. Healthy peers
                    # can still settle and refill their own slots.
                    readers.submit(close_after, trial, None)
                    del active[trial_id]
                    continue
                if observed is None:
                    continue
                row = cast(dict[str, Any], observed.to_dict())
                if row != trial.last:
                    _update_state(root, lambda runs: _record_observation(runs[trial_id], row))
                    trial.last = row
                if (row.get("admission") or {}).get("state") == "BLOCKED":
                    outcome = _run_outcome(trial.available, observed, wait=False, deadline=deadline)
                    _update_state(root, lambda runs: _record_observation(runs[trial_id], row, outcome.cleanup))
                    return
                if _terminal(row):
                    end = monotonic() + selection.startup_seconds
                    cleaning[trial_id] = trial, observed, min(end, deadline) if deadline is not None else end
                    del active[trial_id]
                    completed = True
            # A newly free slot goes to the next trial before terminal cleanup.
            if completed:
                continue
            for trial_id, (finished, observed, end) in tuple(cleaning.items()):
                if trial_id not in cleanup_steps:
                    cleanup_steps[trial_id] = cleaners.submit(cleanup_step, finished, observed, end)
                if not cleanup_steps[trial_id].done():
                    continue
                cleanup = cleanup_steps.pop(trial_id).result()
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
        detached.set()
        for trial_id, trial in active.items():
            pending = reads.get(trial_id)
            if pending is not None:
                pending.cancel()
            readers.submit(close_after, trial, pending)
        for trial_id, (trial, _, _) in cleaning.items():
            pending = cleanup_steps.get(trial_id)
            if pending is not None:
                pending.cancel()
            cleaners.submit(close_after, trial, pending)
        readers.shutdown(wait=False)
        cleaners.shutdown(wait=False)
