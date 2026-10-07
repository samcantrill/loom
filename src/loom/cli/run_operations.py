"""CLI receipts and connect-only observation/cancellation of native run IDs."""

from __future__ import annotations

import argparse
import json
import math
import shlex
import sys
import time
from dataclasses import replace
from collections.abc import Mapping
from typing import TYPE_CHECKING, TextIO

from loom.cli.errors import CliError, ExitCode
from loom.cli.formatting import format_json_envelope
from loom.serialization import PlainData

if TYPE_CHECKING:
    from loom.coordinator import RunObservation
    from loom.deployment import DeploymentSelection
    from loom.queue.errors import QueueError


def _follow_command(operation_id: str, deployment: str) -> str:
    return shlex.join([
        "loom", "runs", "follow", "--operation-id", operation_id,
        "--deployment", deployment,
    ])


def emit_reference(operation_id: str, selection: DeploymentSelection) -> None:
    """Flush a selected identity before dispatch; it does not establish admission."""
    connection = selection.connection
    if connection is None and selection.coordinator is not None:
        connection = selection.coordinator.config
    reference = {
        "operation_id": operation_id, "deployment": str(selection.path),
        "connection_selection": None if connection is None else str(connection),
    }
    sys.stderr.write("operation reference: " + json.dumps(reference, sort_keys=True) + "\n")
    sys.stderr.write("observe: " + _follow_command(operation_id, str(selection.path)) + "\n")
    sys.stderr.flush()


def operation_error(
    error: QueueError, operation_id: str, deployment: str, *, action: str = "run"
) -> CliError:
    """Retain the caller ID and the native outcome, including uncertain replies."""
    from loom.coordinator import CoordinatorClientError

    hint = _follow_command(operation_id, deployment)
    message = f"{action} {operation_id}: {error}"
    if isinstance(error, CoordinatorClientError) and error.mutation_outcome == "unknown":
        message += f"; outcome unknown; observe with {hint}"
    return CliError(
        message, code=f"cli.{action}.coordinator", exit_code=ExitCode.RUN_STATE,
        context={"operation_id": operation_id, "deployment": deployment},
        hint=hint,
        details={"coordinator": error.to_dict()}
        if isinstance(error, CoordinatorClientError) else None,
    )


def logical_status(observation: RunObservation) -> tuple[str, bool, bool]:
    """Render native logical outcome separately from containment and release."""
    operation, admission = observation.operation, observation.admission
    if operation is not None and operation.state in {"failed", "conflict", "cancelled"}:
        return operation.state, True, True
    if admission is not None:
        state = admission.state.value
        return state, state in {"SUCCEEDED", "FAILED", "CANCELLED", "BLOCKED"}, state in {
            "FAILED", "CANCELLED", "BLOCKED",
        }
    return "unobserved" if operation is None else operation.state, False, False


def _deadline(namespace: argparse.Namespace) -> float | None:
    from loom.queue.errors import QueueConfigError

    timeout = namespace.timeout_seconds
    if timeout is None:
        return None
    if not math.isfinite(timeout) or timeout <= 0:
        raise QueueConfigError("observation timeout must be positive finite seconds")
    return time.monotonic() + timeout


def _duration(deadline: float | None) -> float:
    return 25.0 if deadline is None else min(25.0, max(0.0, deadline - time.monotonic()))


def _facts(value: PlainData) -> PlainData:
    if isinstance(value, Mapping):
        return {key: _facts(item) for key, item in value.items() if key not in {"observed_at", "as_of"}}
    if isinstance(value, (tuple, list)):
        return [_facts(item) for item in value]
    return value


def _render_observation(observation: RunObservation, stream: TextIO) -> None:
    state, _, _ = logical_status(observation)
    stream.write(f"run {observation.operation_id}: {state}\n")
    inspection = observation.inspection
    if inspection is not None:
        payload = inspection.to_dict()
        axes = payload.get("axes")
        if isinstance(axes, list):
            for axis in axes:
                if isinstance(axis, Mapping):
                    stream.write(
                        f"{axis['name']}: {axis['state']} "
                        f"({axis['owner']}; {axis['availability']}; {axis['freshness']})\n"
                    )
        else:
            stream.write("inspection: " + json.dumps(payload, sort_keys=True) + "\n")
    stream.write("observer cleanup: coordinator borrowed\n")
    stream.flush()


def handle_follow(namespace: argparse.Namespace) -> int:
    """Follow existing native facts; interruption closes only this connection."""
    from loom.deployment import load_deployment, connect_deployment
    from loom.queue.errors import QueueError

    operation_id = namespace.operation_id
    observation = None
    detached = None
    deadline: float | None = None
    try:
        deadline = _deadline(namespace)
        selection = load_deployment(namespace.deployment)
        with connect_deployment(selection) as client:
            connection = client._native_call("handshake", {}, deadline=deadline)
            previous = None
            while True:
                if deadline is not None and time.monotonic() >= deadline:
                    detached = "timeout"
                    break
                for snapshot in client._run_observation_steps(
                    operation_id, connection,
                    deadline=time.monotonic() + _duration(deadline),
                ):
                    observation = snapshot if observation is None else replace(
                        snapshot, admission=snapshot.admission or observation.admission,
                        inspection=snapshot.inspection or observation.inspection,
                    )
                assert observation is not None
                key = _facts(observation.to_dict())
                if key != previous:
                    _render_observation(
                        observation, sys.stderr if namespace.output_format == "json" else sys.stdout
                    )
                    previous = key
                _, terminal, _ = logical_status(observation)
                if terminal:
                    break
                owner = observation.connection.coordinator_id
                # Native waits retain their absolute transport bound. The CLI
                # catches interruption outside the snapshot and wait reads.
                if observation.admission is None:
                    client._wait_native(
                        "wait_operation", {"operation_id": operation_id},
                        _duration(deadline), owner, terminal_deadline=deadline,
                    )
                else:
                    admission = observation.admission
                    client._wait_native(
                        "wait_admission", {
                            "admission_id": admission.admission_id,
                            "expected_revision": admission.revision,
                        }, _duration(deadline), owner, terminal_deadline=deadline,
                    )
    except (KeyboardInterrupt, EOFError):
        detached = "interrupted"
    except QueueError as exc:
        from loom.coordinator import CoordinatorClientError

        if (
            isinstance(exc, CoordinatorClientError) and exc.code == "deadline_exceeded"
            and deadline is not None and time.monotonic() >= deadline
        ):
            detached = "timeout"
        else:
            raise operation_error(exc, operation_id, namespace.deployment, action="runs.follow") from exc
    _, _, failed = logical_status(observation) if observation is not None else ("unobserved", False, False)
    payload = {
        "operation_id": operation_id, "detached": detached,
        "observation": None if observation is None else observation.to_dict(),
    }
    if namespace.output_format == "json":
        sys.stdout.write(format_json_envelope(
            schema_version="loom.cli.runs.follow.v1", ok=not failed,
            warnings=[], payload_name="result", payload=payload,
        ))
    elif detached is not None:
        sys.stdout.write(f"observation detached: {detached}; work continues under native ownership\n")
    return int(ExitCode.RUN_FAILED if failed else ExitCode.SUCCESS)


def _target(result: PlainData) -> PlainData:
    if not isinstance(result, Mapping):
        return None
    for key in ("admission", "binding", "prepared_run"):
        value = result.get(key)
        if isinstance(value, Mapping) and value.get("run_uri") is not None:
            return value["run_uri"]
    return None


def handle_cancel(namespace: argparse.Namespace) -> int:
    """Display possible shared-target scope, then request native cancellation."""
    from loom.deployment import load_deployment, connect_deployment
    from loom.queue.errors import QueueError

    operation_id = namespace.operation_id
    try:
        deadline = _deadline(namespace)
        selection = load_deployment(namespace.deployment)
        with connect_deployment(selection) as client:
            connection = client._native_call("handshake", {}, deadline=deadline)
            observation = next(client._run_observation_steps(
                operation_id, connection,
                deadline=time.monotonic() + _duration(deadline),
            ))
            assert observation.operation is not None
            preview = {
                "operation_id": operation_id,
                "resolved_target": _target(observation.operation.result),
                "scope": "resolved_target_and_all_observers_if_bound",
            }
            sys.stderr.write("cancellation scope: " + json.dumps(preview, sort_keys=True) + "\n")
            sys.stderr.flush()
            control = client.cancel_run_operation(
                operation_id, expected_coordinator_id=observation.connection.coordinator_id,
                deadline=deadline,
            )
    except QueueError as exc:
        raise operation_error(exc, operation_id, namespace.deployment, action="runs.cancel") from exc
    payload = {
        **preview,
        "resolved_target": _target(control.result) or preview["resolved_target"],
        "cancellation_operation_id": control.operation_id,
        "cancellation": control.to_dict(),
        "containment": "not_established_by_acknowledgement",
    }
    failed = control.state in {"failed", "conflict"}
    if namespace.output_format == "json":
        sys.stdout.write(format_json_envelope(
            schema_version="loom.cli.runs.cancel.v1", ok=not failed,
            warnings=[], payload_name="result", payload=payload,
        ))
    else:
        sys.stdout.write(f"cancel {operation_id}: {control.operation_id} ({control.state})\n")
        sys.stdout.write(f"resolved target: {payload['resolved_target']}; scope: {payload['scope']}\n")
        sys.stdout.write("acknowledgement does not establish containment; observe the native cancellation operation\n")
    return int(ExitCode.RUN_STATE if failed else ExitCode.SUCCESS)


def handle_explain(namespace: argparse.Namespace) -> int:
    """Read one bounded native explanation without starting a service."""
    from loom.deployment import load_deployment, connect_deployment
    from loom.queue.errors import QueueError

    try:
        _deadline(namespace)
        selection = load_deployment(namespace.deployment)
        with connect_deployment(selection) as client:
            result = client.explain_run(
                namespace.operation_id, timeout_seconds=namespace.timeout_seconds or 25.0,
                deployment=namespace.deployment,
            )
    except QueueError as exc:
        raise operation_error(exc, namespace.operation_id, namespace.deployment, action="runs.explain") from exc
    missing = result.summary == "not_found"
    if namespace.output_format == "json":
        sys.stdout.write(format_json_envelope(
            schema_version="loom.cli.runs.explain.v1", ok=not missing,
            warnings=[], payload_name="result", payload=result.to_dict(),
        ))
    else:
        sys.stdout.write(result.format_text() + "\n")
    return int(ExitCode.RUN_STATE if missing else ExitCode.SUCCESS)
