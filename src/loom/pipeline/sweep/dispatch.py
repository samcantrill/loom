"""Sweep trials over durable native run operations.

The sweep manifest owns exact request intent before transmission. The coordinator
owns accepted execution; reconnecting a sweep never authorizes a failed retry.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from loom.serialization import PlainData, thaw_plain_data

from .errors import SweepProtocolError
from .manifest import SWEEP_MANIFEST_FILE_NAME, read_sweep_manifest
from .runner import (
    _sweep_lock,
    check_existing_sweep_plan,
    trial_override_expressions,
    write_sweep_plan,
)
from .status import SweepStatusSummary, build_sweep_status

if TYPE_CHECKING:
    from loom.coordinator import CoordinatorClient, RunRequest
    from loom.queue.local_daemon import LocalDaemonAdmission, LocalDaemonOperation
    from .runner import SweepPlan
    from .trials import SweepTrialRecord


def _update_state[T](root: Path, update: Callable[[dict[str, Any]], T], *, skip_none: bool = False) -> T:
    # Lock only manifest read/modify/write, never workers or network observation.
    root.mkdir(parents=True, exist_ok=True)
    with _sweep_lock(root):
        manifest = read_sweep_manifest(root / SWEEP_MANIFEST_FILE_NAME)
        metadata = cast(dict[str, Any], thaw_plain_data(manifest.metadata))
        runs = metadata.setdefault("native_runs", {})
        result = update(runs)
        if skip_none and result is None:
            return result
        payload = replace(manifest, metadata=metadata).to_dict()
        temporary = root / (".sweep-" + uuid4().hex)
        try:
            with temporary.open("w") as stream:
                json.dump(payload, stream, sort_keys=True, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, root / SWEEP_MANIFEST_FILE_NAME)
            directory = os.open(root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)
        return result


def _retain_trial(
    runs: dict[str, Any], trial: SweepTrialRecord, request_template: RunRequest,
    deployment: str | Path,
) -> RunRequest:
    from loom.coordinator import RunRequest

    if trial.run_uri is None:
        raise SweepProtocolError("native sweep requires a planned trial run_uri")
    options = cast(
        dict[str, PlainData],
        thaw_plain_data(request_template.preparation.run_options),
    )
    if options.get("run_uri") not in (None, trial.run_uri):
        raise SweepProtocolError("template run_uri conflicts with planned trial")
    options["run_uri"] = trial.run_uri
    preparation = replace(
        request_template.preparation,
        run_name=trial.trial_id,
        overrides=request_template.preparation.overrides
        + trial_override_expressions(trial.proposal_overrides),
        run_options=options,
    )
    old = runs.get(trial.trial_id)
    request = RunRequest(
        replace(
            preparation,
            operation_id=(
                old["request"]["preparation"]["operation_id"]
                if old
                else "sweep-" + uuid4().hex
            ),
        ),
        old["request"]["queue_item_id"] if old else "sweep-" + uuid4().hex,
    )
    intent = {
        "request": request.to_dict(),
        "deployment": str(Path(deployment).resolve()),
    }
    if old is not None and any(
        old[key] != value for key, value in intent.items()
    ):
        raise SweepProtocolError(
            "native trial intent conflicts with retained request"
        )
    if old is None:
        runs[trial.trial_id] = intent
    return request


def _reserve_trial(runs, trial, template, deployment):
    previous = runs.get(trial.trial_id)
    request = _retain_trial(runs, trial, template, deployment)
    if previous is not None and not _accepted(previous):
        if previous.get("dispatch_failed"):
            previous.update(dispatch_failed=False, error=None)
        else:
            # A previous sender may have committed, or may still be sending.
            # A local refusal of this attempt cannot resolve that other exchange.
            previous["acceptance_unresolved"] = True
    return request


def _terminal(observation: dict[str, Any]) -> bool:
    return (
        (observation.get("admission") or {}).get("state") in {"SUCCEEDED", "FAILED", "CANCELLED"}
        or (observation.get("operation") or {}).get("state") in {"failed", "cancelled", "conflict"}
    )


def _occupies_slot(record: dict[str, Any]) -> bool:
    return not record.get("dispatch_failed") and not _terminal(record.get("observation") or {})


def _accepted(record) -> bool:
    observation = record.get("observation") or {}
    return bool(observation.get("operation") or observation.get("admission") or record.get("cancellation_operation_id"))


def _record_failure(record, error: Exception) -> bool:
    from loom.coordinator import CoordinatorClientError

    uncertain = isinstance(error, (ConnectionError, TimeoutError)) or (
        isinstance(error, CoordinatorClientError) and (
            error.mutation_outcome in {"unknown", "applied"} or error.code in {"unavailable", "deadline_exceeded"}
        )
    )
    if _accepted(record):
        return _occupies_slot(record)
    uncertain = uncertain or bool(record.get("acceptance_unresolved"))
    record.update(error=str(error), dispatch_failed=not uncertain)
    return uncertain


def _record_observation(record, observation, cleanup=None):
    # A passive watcher can finish after the dispatcher's terminal read or an
    # explicit retry. Native admission revisions order those observations.
    previous = record.get("observation") or {}
    prior = previous.get("admission") or {}
    current = observation.get("admission") or {}
    if prior and (not current or prior.get("revision", 0) > current.get("revision", 0)):
        return
    if _terminal(previous) and not _terminal(observation) and not (
        current and current.get("revision", 0) > prior.get("revision", 0)
    ):
        return
    if cleanup is None and _terminal(observation) and not _terminal(previous):
        # Provisional cleanup at acceptance no longer describes the terminal cut.
        record.pop("cleanup", None)
    record.update(observation=observation, error=None, dispatch_failed=False)
    if _accepted(record):
        record.pop("acceptance_unresolved", None)
    if cleanup is not None:
        record["cleanup"] = dict(cleanup)


def run_sweep(
    plan: SweepPlan,
    *,
    request_template: RunRequest,
    deployment: str | Path,
    sweep_dir: str | Path,
    wait: bool = True,
    max_in_flight: int = 1,
    timeout_seconds: float | None = None,
) -> SweepStatusSummary:
    """Dispatch trials in order through :func:`loom.run`, continuing after failures.

    The exact-mode native template selects importable project config, overlays,
    sparse run options and source/profile. Trial overrides follow base overrides. Each planned
    run URI must match the deployment's protected run root plus its trial ID;
    conflicting placement fails at native preparation without relocating outputs.
    Exact requests and IDs are persisted in sweep-manifest metadata before send.
    Timeout detaches observation; KeyboardInterrupt stops selecting further trials.
    A waiting window above one admits independent trials before terminal observation.
    Its timeout covers the invocation. An uncertain request continues to occupy a slot.
    Replay retains original intent and never requests failed-admission retry.
    """
    from loom import run
    from loom.coordinator import RunRequest

    if not isinstance(request_template, RunRequest):
        raise SweepProtocolError("request_template must be a native RunRequest")
    if request_template.mode != "exact":
        raise SweepProtocolError("native sweeps require exact run intent")
    if type(max_in_flight) is not int or max_in_flight < 1:
        raise SweepProtocolError("max_in_flight must be a positive integer")
    root = Path(sweep_dir)
    compatibility = check_existing_sweep_plan(root, expected_plan=plan)
    if compatibility.diagnostics:
        raise SweepProtocolError(
            "incompatible existing sweep plan: "
            + ", ".join(item.code for item in compatibility.diagnostics)
        )
    if compatibility.sweep_manifest is None:
        write_sweep_plan(plan, root)
    if wait and max_in_flight > 1:
        from ._window import run_waiting_window

        run_waiting_window(plan, request_template, deployment, root, max_in_flight, timeout_seconds)
        manifest = read_sweep_manifest(root / SWEEP_MANIFEST_FILE_NAME)
        return build_sweep_status(replace(plan, sweep_manifest=manifest))

    for trial in plan.trials:
        def retain(runs):
            row = runs.get(trial.trial_id)
            if wait and (row is None or row.get("dispatch_failed")) and any(
                _occupies_slot(other) for other in runs.values()
            ):
                return None
            request = _reserve_trial(runs, trial, request_template, deployment)
            return request, _observed_owner(runs[trial.trial_id])

        retained = _update_state(root, retain, skip_none=True)
        if retained is None:
            break
        request, owner = retained
        try:
            outcome = run(
                request,
                deployment=deployment,
                wait=wait,
                timeout_seconds=timeout_seconds,
                expected_coordinator_id=owner,
            )
            observation = cast(dict[str, Any], outcome.observation.to_dict())
            _update_state(
                root,
                lambda runs: _record_observation(runs[trial.trial_id], observation, outcome.cleanup),
            )
            if wait and not _terminal(observation):
                break
        except Exception as exc:  # A failed trial must not discard later experiments.
            uncertain = _update_state(root, lambda runs, error=exc: _record_failure(runs[trial.trial_id], error))
            if wait and uncertain:
                break
    manifest = read_sweep_manifest(root / SWEEP_MANIFEST_FILE_NAME)
    return build_sweep_status(replace(plan, sweep_manifest=manifest))


def observe_sweep(
    plan: SweepPlan, *, client: CoordinatorClient, sweep_dir: str | Path
) -> SweepStatusSummary:
    """Refresh retained operations without submitting any unsent trial or retry.

    A saved request can precede native acceptance. If its operation is absent and
    no observation or cancellation control has established acceptance, retain its
    local outcome and continue. Missing accepted work and other native errors
    propagate to the caller.
    """
    from loom.coordinator import CoordinatorClientError

    root = Path(sweep_dir)
    manifest = read_sweep_manifest(root / SWEEP_MANIFEST_FILE_NAME)
    for trial_id, record in cast(
        dict[str, Any], manifest.metadata.get("native_runs", {})
    ).items():
        operation_id = record["request"]["preparation"]["operation_id"]
        try:
            observation = client.observe_run(
                operation_id,
                wait=False,
                expected_coordinator_id=_observed_owner(record),
            ).to_dict()
        except CoordinatorClientError as exc:
            previous = record.get("observation") or {}
            if (
                exc.code == "not_found"
                and exc.operation == "operation"
                and exc.ids.get("operation_id") == operation_id
                and previous.get("operation") is None
                and previous.get("admission") is None
                and record.get("cancellation_operation_id") is None
            ):
                # Intent is saved before send. Preserve its uncertainty/failure
                # and any newer concurrent observation without writing a stale row.
                continue
            raise
        _update_state(
            root,
            lambda runs: _record_observation(runs[trial_id], observation),
        )
    return build_sweep_status(
        replace(
            plan, sweep_manifest=read_sweep_manifest(root / SWEEP_MANIFEST_FILE_NAME)
        )
    )


def cancel_sweep_trial(
    sweep_dir: str | Path, trial_id: str, *, client: CoordinatorClient
) -> LocalDaemonOperation:
    """Cancel one selected native operation; return its independent control reference."""
    root = Path(sweep_dir)
    record = cast(
        dict[str, Any],
        read_sweep_manifest(root / SWEEP_MANIFEST_FILE_NAME).metadata["native_runs"],
    )[trial_id]
    control = client.cancel_run_operation(
        record["request"]["preparation"]["operation_id"],
        expected_coordinator_id=_observed_owner(record),
    )
    _update_state(
        root,
        lambda runs: runs[trial_id].update(
            cancellation_operation_id=control.operation_id
        ),
    )
    return control


def retry_sweep_trial(
    sweep_dir: str | Path,
    trial_id: str,
    *,
    client: CoordinatorClient,
    retry_failed_revision: int,
) -> LocalDaemonAdmission:
    """Explicitly retry an observed failed admission through its native capability.

    Only authorities supporting native failed retry can accept this request. The
    exact retry reference is retained before sending; ordinary sweep replay does
    not resend this authorization or infer a revision.
    """
    from loom.queue import LocalDaemonAdmissionRequest

    root = Path(sweep_dir)

    def retain(runs):
        record = runs[trial_id]
        admission = record["observation"]["admission"]
        request = LocalDaemonAdmissionRequest(
            record["request"]["queue_item_id"],
            admission["run_uri"],
            retry_failed_revision,
        )
        record["retry_request"] = request.to_dict()
        return request, _observed_owner(record)

    request, owner = _update_state(root, retain)
    return client.submit(request, expected_coordinator_id=owner)


def _observed_owner(record: dict[str, Any]) -> str | None:
    return record.get("coordinator_id") or (record.get("observation") or {}).get("connection", {}).get("coordinator_id")


__all__ = ["run_sweep", "observe_sweep", "cancel_sweep_trial", "retry_sweep_trial"]
