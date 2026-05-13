"""Local managed dispatch adapter for queue controllers."""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from loom.pipeline.execution.resource_admission import (
    DEFAULT_RESOURCE_LEASE_TTL_SECONDS,
    ResourceAdmissionDecision,
    ResourceAdmissionRequest,
    ResourceAdmissionStatus,
    ResourceLeaseRequest,
    acquire_resource_admission,
    release_resource_admission,
)
from loom.pipeline.stores import LifecycleReason, WorkspaceCoordinationStore
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.serialization.errors import PlainDataError
from loom.timestamps import utc_timestamp

from .controller import (
    QueueDispatchCancellation,
    QueueDispatchInspection,
    QueueDispatchResult,
)
from .errors import QueueServiceError
from .models import QueueItem, QueueItemStatus

LOCAL_ADAPTER_NAME = "local"


class LocalProcess(Protocol):
    """Process handle used by the local dispatch adapter."""

    pid: int
    pgid: int

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


class LocalProcessRunner(Protocol):
    """Launch local commands into their own process groups."""

    def start(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> LocalProcess: ...


@dataclass(frozen=True, slots=True)
class LocalLaunchCommand:
    """Trusted command captured in a launch contract snapshot."""

    argv: tuple[str, ...]
    cwd: str | None = None
    env: Mapping[str, str] | None = None


@dataclass(slots=True)
class _ActiveLocalDispatch:
    process: LocalProcess
    admission: ResourceAdmissionDecision


class SubprocessLocalProcessRunner:
    """POSIX process-group runner for local queue dispatch."""

    def start(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> LocalProcess:
        process_env = None if env is None else {**os.environ, **dict(env)}
        popen = subprocess.Popen(  # noqa: S603
            list(argv),
            cwd=cwd,
            env=process_env,
            start_new_session=True,
        )
        return _PopenLocalProcess(popen)


class _PopenLocalProcess:
    def __init__(self, popen: subprocess.Popen[bytes]) -> None:
        self._popen = popen
        self.pid = popen.pid
        self.pgid = os.getpgid(popen.pid)

    def poll(self) -> int | None:
        return self._popen.poll()

    def terminate(self) -> None:
        try:
            os.killpg(self.pgid, signal.SIGTERM)
        except ProcessLookupError:
            return

    def kill(self) -> None:
        try:
            os.killpg(self.pgid, signal.SIGKILL)
        except ProcessLookupError:
            return


class LocalQueueDispatchAdapter:
    """Dispatch locally managed queue items with authority resource leases."""

    adapter_name = LOCAL_ADAPTER_NAME

    def __init__(
        self,
        *,
        workspace_id: str,
        coordination_store: WorkspaceCoordinationStore,
        owner_id: str,
        process_runner: LocalProcessRunner | None = None,
        current_drift_inputs: Mapping[str, PlainData] | None = None,
        lease_ttl_seconds: int = DEFAULT_RESOURCE_LEASE_TTL_SECONDS,
        wait_timeout_seconds: float = 0.0,
        clock: Callable[[], str] = utc_timestamp,
    ) -> None:
        if not isinstance(workspace_id, str) or not workspace_id:
            raise QueueServiceError("workspace_id must be a non-empty string")
        if not isinstance(owner_id, str) or not owner_id:
            raise QueueServiceError("owner_id must be a non-empty string")
        self.workspace_id = workspace_id
        self.coordination_store = coordination_store
        self.owner_id = owner_id
        self.process_runner = process_runner or SubprocessLocalProcessRunner()
        self.current_drift_inputs = _plain_mapping(
            {} if current_drift_inputs is None else current_drift_inputs,
            "current_drift_inputs",
        )
        self.lease_ttl_seconds = lease_ttl_seconds
        self.wait_timeout_seconds = wait_timeout_seconds
        self._clock = clock
        self._active: dict[str, _ActiveLocalDispatch] = {}

    def dispatch(self, item: QueueItem) -> QueueDispatchResult:
        drift_evidence = self._drift_evidence(item)
        if drift_evidence is not None:
            return QueueDispatchResult(
                handle_id=f"local-drift:{item.queue_item_id}:{item.dispatch_attempt}",
                status=QueueItemStatus.FAILED,
                reason="local launch contract drift detected",
                evidence=drift_evidence,
            )
        command = _launch_command(item)
        admission_request = _resource_admission_request(
            item,
            workspace_id=self.workspace_id,
            owner_id=self.owner_id,
            lease_ttl_seconds=self.lease_ttl_seconds,
            wait_timeout_seconds=self.wait_timeout_seconds,
        )
        admission = acquire_resource_admission(
            self.coordination_store,
            admission_request,
        )
        if admission.status is not ResourceAdmissionStatus.ADMITTED:
            return QueueDispatchResult(
                handle_id=f"local-admission:{item.queue_item_id}:{item.dispatch_attempt}",
                status=QueueItemStatus.UNKNOWN,
                reason=admission.reason_code or "local resource admission unavailable",
                evidence={
                    "resource_admission": admission.to_dict(),
                    "local_process_started": False,
                },
            )
        try:
            process = self.process_runner.start(
                command.argv,
                cwd=command.cwd,
                env=command.env,
            )
        except Exception as exc:
            released = self._release_admission(admission, code="local_process_start_failed")
            return QueueDispatchResult(
                handle_id=f"local-start:{item.queue_item_id}:{item.dispatch_attempt}",
                status=QueueItemStatus.FAILED,
                reason="local process start failed",
                evidence={
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                    "resource_admission": admission.to_dict(),
                    "released_resource_leases": released,
                    "local_process_started": False,
                },
            )
        handle_id = f"local:{item.queue_item_id}:{item.dispatch_attempt}:{process.pid}"
        self._active[handle_id] = _ActiveLocalDispatch(
            process=process,
            admission=admission,
        )
        return QueueDispatchResult(
            handle_id=handle_id,
            status=QueueItemStatus.DISPATCHED,
            reason="local process dispatched",
            evidence={
                "adapter": LOCAL_ADAPTER_NAME,
                "pid": process.pid,
                "pgid": process.pgid,
                "argv": list(command.argv),
                "cwd": command.cwd,
                "resource_admission": admission.to_dict(),
                "dispatched_at": self._clock(),
            },
            complete=False,
        )

    def inspect(self, item: QueueItem) -> QueueDispatchInspection:
        handle_id = _dispatch_handle_id(item)
        active = self._active.get(handle_id)
        if active is None:
            return QueueDispatchInspection(
                status=QueueItemStatus.UNKNOWN,
                reason="local dispatch recovery needed",
                evidence={
                    "handle_id": handle_id,
                    "recovery_needed": True,
                    "resource_leases_released": False,
                },
                terminal=True,
            )
        returncode = active.process.poll()
        if returncode is None:
            return QueueDispatchInspection(
                status=QueueItemStatus.DISPATCHED,
                reason="local process active",
                evidence={
                    "handle_id": handle_id,
                    "pid": active.process.pid,
                    "pgid": active.process.pgid,
                },
                terminal=False,
            )
        active = self._active.pop(handle_id)
        released = self._release_admission(
            active.admission,
            code="local_process_completed",
        )
        status = QueueItemStatus.SUCCEEDED if returncode == 0 else QueueItemStatus.FAILED
        reason = "local process succeeded" if returncode == 0 else "local process failed"
        return QueueDispatchInspection(
            status=status,
            reason=reason,
            evidence={
                "handle_id": handle_id,
                "pid": active.process.pid,
                "pgid": active.process.pgid,
                "returncode": returncode,
                "released_resource_leases": released,
            },
            terminal=True,
        )

    def cancel(
        self,
        item: QueueItem,
        *,
        requested_by: str,
        reason: str,
    ) -> QueueDispatchCancellation:
        handle_id = _dispatch_handle_id(item)
        active = self._active.pop(handle_id, None)
        if active is None:
            return QueueDispatchCancellation(
                reason=reason,
                evidence={
                    "handle_id": handle_id,
                    "recovery_needed": True,
                    "resource_leases_released": False,
                },
            )
        returncode = active.process.poll()
        if returncode is None:
            active.process.terminate()
        released = self._release_admission(
            active.admission,
            code="local_process_cancelled",
        )
        return QueueDispatchCancellation(
            reason=reason,
            evidence={
                "handle_id": handle_id,
                "pid": active.process.pid,
                "pgid": active.process.pgid,
                "requested_by": requested_by,
                "returncode": returncode,
                "terminated_process_group": returncode is None,
                "released_resource_leases": released,
            },
        )

    def _drift_evidence(self, item: QueueItem) -> Mapping[str, PlainData] | None:
        expected = thaw_plain_data(
            item.launch_contract.drift_inputs,
            path="drift_inputs",
        )
        actual = thaw_plain_data(
            self.current_drift_inputs,
            path="current_drift_inputs",
        )
        if expected == actual:
            return None
        return {
            "drift_detected": True,
            "expected_drift_inputs": expected,
            "actual_drift_inputs": actual,
        }

    def _release_admission(
        self,
        admission: ResourceAdmissionDecision,
        *,
        code: str,
    ) -> list[PlainData]:
        released = release_resource_admission(
            self.coordination_store,
            admission,
            reason=LifecycleReason(
                code=code,
                message=f"released local queue resource admission for {admission.request.run_uri}",
            ),
        )
        return [record.to_dict() for record in released]


def _dispatch_handle_id(item: QueueItem) -> str:
    if item.dispatch_handle is None:
        raise QueueServiceError("local item has no dispatch handle")
    return item.dispatch_handle.handle_id


def _launch_command(item: QueueItem) -> LocalLaunchCommand:
    snapshot = item.launch_contract.snapshot
    argv = snapshot.get("argv")
    if not isinstance(argv, Sequence) or isinstance(argv, str) or not argv:
        raise QueueServiceError("local launch snapshot requires non-empty argv")
    normalized_argv = tuple(_string(value, "argv") for value in argv)
    cwd = snapshot.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        raise QueueServiceError("local launch snapshot cwd must be a string or null")
    env_value = snapshot.get("env")
    env = None
    if env_value is not None:
        if not isinstance(env_value, Mapping):
            raise QueueServiceError("local launch snapshot env must be a mapping")
        env = {
            _string(key, "env key"): _string(value, f"env[{key}]")
            for key, value in env_value.items()
        }
    return LocalLaunchCommand(argv=normalized_argv, cwd=cast(str | None, cwd), env=env)


def _resource_admission_request(
    item: QueueItem,
    *,
    workspace_id: str,
    owner_id: str,
    lease_ttl_seconds: int,
    wait_timeout_seconds: float,
) -> ResourceAdmissionRequest:
    resources = tuple(
        ResourceLeaseRequest(resource_key=key, amount=amount)
        for key, amount in item.launch_contract.resources.items()
        if amount > 0
    )
    return ResourceAdmissionRequest(
        run_uri=item.run_uri,
        stage_name=f"queue:{item.queue_item_id}",
        workspace_id=workspace_id,
        owner_id=owner_id,
        resources=resources,
        lease_ttl_seconds=lease_ttl_seconds,
        wait_timeout_seconds=wait_timeout_seconds,
    )


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise QueueServiceError(f"{field} must be a non-empty string")
    return value


def _plain_mapping(value: Mapping[str, PlainData], path: str) -> Mapping[str, PlainData]:
    try:
        frozen = freeze_plain_data(value, path=path)
    except PlainDataError as exc:
        raise QueueServiceError(str(exc)) from exc
    if not isinstance(frozen, Mapping):
        raise QueueServiceError(f"{path} must be a mapping")
    return cast(Mapping[str, PlainData], frozen)


__all__ = [
    "LOCAL_ADAPTER_NAME",
    "LocalLaunchCommand",
    "LocalProcess",
    "LocalProcessRunner",
    "LocalQueueDispatchAdapter",
    "SubprocessLocalProcessRunner",
]
