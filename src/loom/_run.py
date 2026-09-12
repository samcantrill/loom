"""Shared availability, native run acceptance, observation and cleanup composition."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import json
import math
from pathlib import Path
import sqlite3
import time
from typing import cast
from uuid import uuid4

from loom.coordinator import CoordinatorClientError, RunObservation, RunRequest
from loom.deployment import AvailableDeployment, ensure_available, load_deployment
from loom.queue.errors import QueueConfigError, QueueError
from loom.queue.local_daemon import LocalDaemonAdmissionState
from loom.serialization import PlainData


@dataclass(frozen=True)
class RunOutcome:
    """Native run facts and separate per-role cleanup evidence.

    Detached or timed-out callers keep accepted identities. Cleanup never changes
    authority results and never cancels another run or kills an unresolved worker.
    """

    observation: RunObservation
    cleanup: Mapping[str, PlainData]

    def to_dict(self) -> dict[str, PlainData]:
        return {**self.observation.to_dict(), "cleanup": dict(self.cleanup)}


def _process_receipt(root: Path) -> tuple[str, dict[str, PlainData]]:
    with sqlite3.connect(
        f"{(root / 'control.sqlite').as_uri()}?mode=ro", uri=True
    ) as conn:
        rows = dict(
            conn.execute(
                "SELECT key,value FROM root_metadata WHERE key IN ('service_lifetime', 'service_process')"
            )
        )
    if rows.get("service_lifetime") != "run":
        return "persistent/borrowed", {}
    value = json.loads(rows.get("service_process", "{}"))
    if value.get("stopped"):
        process = Path(f"/proc/{value['pid']}/stat")
        try:
            current = process.read_text().split()
            alive = current[21] == value["started"] and current[2] != "Z"
        except FileNotFoundError:
            alive = False
        if not alive:
            return "stopped", value
    return "running", value


def _cleanup(
    available: AvailableDeployment, observation: RunObservation, deadline: float
) -> dict[str, PlainData]:
    roles = available.roles
    result: dict[str, PlainData] = {}
    if "coordinator" not in roles:
        result["coordinator"] = {"state": "persistent/borrowed"}
    while True:
        pending = False
        retained = None
        blocked = None
        try:
            projection = available.client._native_call(
                "service_lifetime", {}, available.connection_id, deadline=deadline
            )
            retained, blocked = projection["retained"], projection["cleanup_blocked"]
        except CoordinatorClientError:
            pass
        for name, role in roles.items():
            root = Path(role["identity"]["root"])
            if name == "coordinator":
                root /= "coordinator"
            try:
                state, evidence = _process_receipt(root)
            except (OSError, sqlite3.Error, ValueError) as exc:
                state, evidence = "cleanup-blocked", {"diagnostic": str(exc)}
            if state == "running":
                if blocked is not None:
                    state = "cleanup-blocked"
                    evidence = {**evidence, "diagnostic": blocked}
                elif retained:
                    state = "retained-for-other-work"
                elif time.monotonic() >= deadline:
                    state = "cleanup-blocked"
                else:
                    pending = True
            result[name] = cast(PlainData, {"state": state, "evidence": evidence})
        if not pending:
            return result
        time.sleep(min(0.05, max(0, deadline - time.monotonic())))


def run(
    request: RunRequest,
    *,
    deployment: str | Path,
    wait: bool = True,
    timeout_seconds: float | None = None,
) -> RunOutcome:
    """Start/reuse selected roles and accept exactly the supplied native intent.

    Startup and dispatch share the caller deadline and the deployment startup
    limit. Observation timeout/interrupt detaches; cancellation is always explicit.
    Config and overlays must be in the selected project-relative source closure.
    """
    if not isinstance(request, RunRequest) or not isinstance(wait, bool):
        raise QueueConfigError("run request/wait is invalid")
    if timeout_seconds is not None and (
        type(timeout_seconds) not in (int, float)
        or not math.isfinite(timeout_seconds)
        or timeout_seconds < 0
    ):
        raise QueueConfigError("run timeout is invalid")
    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
    selection = load_deployment(deployment)
    preparation = request.preparation
    if (
        preparation.source != selection.source
        or preparation.preparation_profile != selection.preparation_profile
    ):
        raise QueueConfigError("run preparation conflicts with deployment selection")
    for path in (preparation.config_path, *preparation.overlays):
        if not any(
            include == "." or path == include or path.startswith(include + "/")
            for include in selection.source.include
        ):
            raise QueueConfigError(
                "experiment path is outside the preparation source closure"
            )
    startup_deadline = min(
        time.monotonic() + selection.startup_seconds,
        deadline if deadline is not None else math.inf,
    )
    available = ensure_available(
        selection, attachment_id=preparation.operation_id, deadline=startup_deadline
    )
    release_deadline = deadline
    try:
        operation = available.client._native_call(
            "start_run",
            {"request": request.to_dict()},
            available.connection_id,
            deadline=startup_deadline,
        )
        observation = RunObservation(
            preparation.operation_id, operation, None, None, available.description
        )
        observation_deadline = deadline
        if selection.wait_seconds is not None:
            observation_deadline = min(
                time.monotonic() + selection.wait_seconds,
                deadline if deadline is not None else math.inf,
            )
        if wait:
            release_deadline = observation_deadline
            while True:
                try:
                    timeout = (
                        None
                        if observation_deadline is None
                        else max(0, observation_deadline - time.monotonic())
                    )
                    observation = available.client.observe_run(
                        preparation.operation_id, timeout_seconds=timeout
                    )
                    if observation.operation is None:
                        observation = replace(observation, operation=operation)
                    break
                except (KeyboardInterrupt, EOFError):
                    break
                except CoordinatorClientError as exc:
                    if exc.code == "deadline_exceeded":
                        break
                    if exc.code != "unavailable":
                        raise
                    if (
                        observation_deadline is not None
                        and time.monotonic() >= observation_deadline
                    ):
                        break
                    # Reopen the same bound owners to read completed native facts;
                    # observation recovery never sends a new run request.
                    available.client.close()
                    try:
                        available = ensure_available(
                            selection,
                            attachment_id="observe-" + uuid4().hex,
                            deadline=observation_deadline,
                        )
                    except CoordinatorClientError as reopen_error:
                        if reopen_error.code in {"unavailable", "deadline_exceeded"}:
                            break
                        raise
        try:
            available.release(release_deadline)
        except QueueError:
            pass
        terminal = (
            observation.operation is not None
            and observation.operation.state in {"failed", "cancelled", "conflict"}
        )
        terminal = terminal or (
            observation.admission is not None
            and observation.admission.state
            in {
                LocalDaemonAdmissionState.SUCCEEDED,
                LocalDaemonAdmissionState.FAILED,
                LocalDaemonAdmissionState.CANCELLED,
            }
        )
        if wait and terminal:
            cleanup_deadline = min(
                time.monotonic() + selection.startup_seconds,
                deadline if deadline is not None else math.inf,
            )
            cleanup = _cleanup(available, observation, cleanup_deadline)
        else:
            cleanup = {
                name: {
                    "state": "persistent/borrowed"
                    if role["identity"]["lifetime"] == "persistent"
                    else "retained-for-other-work"
                }
                for name, role in available.roles.items()
            }
            cleanup.setdefault("coordinator", {"state": "persistent/borrowed"})
            if (
                observation.admission is not None
                and observation.admission.state == LocalDaemonAdmissionState.BLOCKED
            ):
                for role in cleanup.values():
                    if role["state"] != "persistent/borrowed":
                        role["state"] = "cleanup-blocked"
        coordinator = available.roles.get("coordinator")
        if coordinator is not None and "agent" in coordinator["ids"]:
            cleanup["agent"] = {
                "state": cast(dict[str, PlainData], cleanup["coordinator"])["state"],
                "cohosted_with": "coordinator",
                "service_id": coordinator["ids"]["agent"],
            }
        return RunOutcome(observation, cast(Mapping[str, PlainData], cleanup))
    finally:
        try:
            available.release(release_deadline)
        except QueueError:
            pass
        available.client.close()
