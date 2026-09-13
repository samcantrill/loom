"""Sweep trials over durable native run operations.

The sweep manifest owns exact request intent before transmission. The coordinator
owns accepted execution; reconnecting a sweep never authorizes a failed retry.
"""

from __future__ import annotations

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


def _update_state(root: Path, update):
    # Lock only manifest read/modify/write, never workers or network observation.
    root.mkdir(parents=True, exist_ok=True)
    with _sweep_lock(root):
        manifest = read_sweep_manifest(root / SWEEP_MANIFEST_FILE_NAME)
        metadata = cast(dict[str, Any], thaw_plain_data(manifest.metadata))
        runs = metadata.setdefault("native_runs", {})
        result = update(runs)
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


def run_sweep(
    plan: SweepPlan,
    *,
    request_template: RunRequest,
    deployment: str | Path,
    sweep_dir: str | Path,
    wait: bool = True,
    timeout_seconds: float | None = None,
) -> SweepStatusSummary:
    """Dispatch trials in order through :func:`loom.run`, continuing after failures.

    The native template selects importable project config, overlays, sparse run
    options and source/profile. Trial overrides follow base overrides. Each planned
    run URI must match the deployment's protected run root plus its trial ID;
    conflicting placement fails at native preparation without relocating outputs.
    Exact requests and IDs are persisted in sweep-manifest metadata before send.
    Timeout detaches observation; KeyboardInterrupt stops selecting further trials.
    Replay retains original intent and never requests failed-admission retry.
    """
    from loom import run
    from loom.coordinator import CoordinatorClientError, RunRequest

    if not isinstance(request_template, RunRequest):
        raise SweepProtocolError("request_template must be a native RunRequest")
    root = Path(sweep_dir)
    compatibility = check_existing_sweep_plan(root, expected_plan=plan)
    if compatibility.diagnostics:
        raise SweepProtocolError(
            "incompatible existing sweep plan: "
            + ", ".join(item.code for item in compatibility.diagnostics)
        )
    if compatibility.sweep_manifest is None:
        write_sweep_plan(plan, root)
    for trial in plan.trials:
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

        def retain(runs):
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

        request = _update_state(root, retain)
        try:
            outcome = run(
                request,
                deployment=deployment,
                wait=wait,
                timeout_seconds=timeout_seconds,
            )
            observation = cast(dict[str, Any], outcome.observation.to_dict())
            _update_state(
                root,
                lambda runs: runs[trial.trial_id].update(
                    observation=observation,
                    cleanup=dict(outcome.cleanup),
                    error=None,
                    dispatch_failed=False,
                ),
            )
            admission = observation.get("admission") or {}
            operation = observation.get("operation") or {}
            if (
                wait
                and admission.get("state") not in {"SUCCEEDED", "FAILED", "CANCELLED"}
                and operation.get("state") not in {"failed", "cancelled", "conflict"}
            ):
                break
        except Exception as exc:  # A failed trial must not discard later experiments.
            error = str(exc)
            uncertain = isinstance(exc, (ConnectionError, TimeoutError)) or (
                isinstance(exc, CoordinatorClientError)
                and exc.code in {"unavailable", "deadline_exceeded"}
            )
            _update_state(
                root,
                lambda runs: runs[trial.trial_id].update(
                    error=error, dispatch_failed=not uncertain
                ),
            )
    manifest = read_sweep_manifest(root / SWEEP_MANIFEST_FILE_NAME)
    return build_sweep_status(replace(plan, sweep_manifest=manifest))


def observe_sweep(
    plan: SweepPlan, *, client: CoordinatorClient, sweep_dir: str | Path
) -> SweepStatusSummary:
    """Refresh retained operations without submitting any unsent trial or retry."""
    root = Path(sweep_dir)
    manifest = read_sweep_manifest(root / SWEEP_MANIFEST_FILE_NAME)
    for trial_id, record in cast(
        dict[str, Any], manifest.metadata.get("native_runs", {})
    ).items():
        observation = client.observe_run(
            record["request"]["preparation"]["operation_id"],
            wait=False,
            expected_coordinator_id=_observed_owner(record),
        ).to_dict()
        _update_state(
            root,
            lambda runs: runs[trial_id].update(
                observation=observation, error=None, dispatch_failed=False
            ),
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
    return (record.get("observation") or {}).get("connection", {}).get("coordinator_id")


__all__ = ["run_sweep", "observe_sweep", "cancel_sweep_trial", "retry_sweep_trial"]
