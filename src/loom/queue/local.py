"""Local managed dispatch adapter for queue controllers."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import inspect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import Protocol, TypedDict, cast
from uuid import uuid4

from loom.pipeline.execution.resource_admission import (
    DEFAULT_RESOURCE_LEASE_TTL_SECONDS,
    ResourceAdmissionDecision,
    ResourceAdmissionRequest,
    ResourceAdmissionStatus,
    ResourceLeaseRequest,
    acquire_resource_admission,
)
from loom.pipeline.stores import (
    CoordinationFailureKind,
    CoordinationStoreError,
    LifecycleReason,
    WorkspaceCoordinationStore,
)
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.serialization.errors import PlainDataError
from loom.timestamps import parse_timestamp, utc_timestamp

from .controller import (
    QueueDispatchCancellation,
    QueueDispatchDisposition,
    QueueDispatchInspection,
    QueueDispatchNonStartCause,
    QueueDispatchResult,
    QueuePreStartCleanupStatus,
)
from .assignments import (
    NoOpResourceAssignmentProvider,
    ResourceAssignment,
    ResourceAssignmentDisposition,
    ResourceAssignmentProvider,
    ResourceAssignmentRequest,
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


class _LogLocalProcessRunner(Protocol):
    def start(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        stdout_path: Path | None = None,
        stderr_path: Path | None = None,
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
    assignment: ResourceAssignment
    next_renew_at: str | None
    safety_deadline_at: str | None
    assignment_safety_deadline_at: str | None
    assignment_released: bool = False
    admission_released: bool = False
    termination_requested: bool = False
    cancellation_requested: bool = False


class _CleanupResult(TypedDict):
    pending: bool
    assignment_released: list[PlainData]
    admission_released: list[PlainData]
    evidence: Mapping[str, PlainData]


class SubprocessLocalProcessRunner:
    """POSIX process-group runner for local queue dispatch."""

    def start(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        stdout_path: Path | None = None,
        stderr_path: Path | None = None,
    ) -> LocalProcess:
        process_env = None if env is None else {**os.environ, **dict(env)}
        stdout = None if stdout_path is None else stdout_path.open("ab")
        stderr = None if stderr_path is None else stderr_path.open("ab")
        try:
            popen = subprocess.Popen(  # noqa: S603
                list(argv),
                cwd=cwd,
                env=process_env,
                start_new_session=True,
                stdout=stdout,
                stderr=stderr,
            )
        finally:
            if stdout is not None:
                stdout.close()
            if stderr is not None:
                stderr.close()
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
        session_id: str | None = None,
        assignment_provider: ResourceAssignmentProvider | None = None,
        log_directory: str | Path | None = None,
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
        self.session_id = session_id or uuid4().hex
        self.assignment_provider = (
            assignment_provider or NoOpResourceAssignmentProvider()
        )
        self.log_directory = (
            Path(log_directory)
            if log_directory is not None
            else Path(".loom") / "queue" / "logs"
        )
        self._active: dict[str, _ActiveLocalDispatch] = {}

    def dispatch(self, item: QueueItem) -> QueueDispatchResult:
        drift_evidence = self._drift_evidence(item)
        if drift_evidence is not None:
            return QueueDispatchResult(
                disposition=QueueDispatchDisposition.NOT_STARTED,
                reason="local.launch_contract_drift",
                evidence=drift_evidence,
                non_start_cause=QueueDispatchNonStartCause.INVALID_OR_UNSUPPORTED,
                pre_start_cleanup_status=QueuePreStartCleanupStatus.NOT_REQUIRED,
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
            if admission.failure_kind is CoordinationFailureKind.CAPACITY:
                return QueueDispatchResult(
                    disposition=QueueDispatchDisposition.NOT_STARTED,
                    reason="resource_admission.capacity_unavailable",
                    evidence={"local_process_started": False},
                    non_start_cause=QueueDispatchNonStartCause.CAPACITY,
                    pre_start_cleanup_status=QueuePreStartCleanupStatus.NOT_REQUIRED,
                )
            if admission.failure_kind is CoordinationFailureKind.INVALID_OR_UNSUPPORTED:
                return QueueDispatchResult(
                    disposition=QueueDispatchDisposition.NOT_STARTED,
                    reason=admission.reason_code
                    or "resource_admission.unsupported_resource",
                    evidence={"local_process_started": False},
                    non_start_cause=QueueDispatchNonStartCause.INVALID_OR_UNSUPPORTED,
                    pre_start_cleanup_status=QueuePreStartCleanupStatus.NOT_REQUIRED,
                )
            return QueueDispatchResult(
                disposition=QueueDispatchDisposition.NOT_STARTED,
                reason=admission.reason_code or "local resource admission unavailable",
                evidence={
                    "local_process_started": False,
                },
                non_start_cause=_non_start_cause(admission.failure_kind),
                pre_start_cleanup_status=QueuePreStartCleanupStatus.NOT_REQUIRED,
            )
        try:
            assignment_decision = self.assignment_provider.acquire(
                ResourceAssignmentRequest(
                    consumer_id=item.queue_item_id,
                    pool_name=item.pool_name,
                    owner_id=self.owner_id,
                    session_id=self.session_id,
                    resources={
                        key: amount
                        for key, amount in item.launch_contract.resources.items()
                        if amount > 0
                    },
                    admitted_lease_ids=tuple(
                        record.lease.lease_id for record in admission.leases
                    ),
                    lease_ttl_seconds=self.lease_ttl_seconds,
                )
            )
        except Exception as exc:  # noqa: BLE001
            cleanup = self._cleanup_pre_start(
                admission=admission,
                assignment=None,
                code="local_assignment_acquire_failed",
            )
            return self._pre_start_cleanup_result(
                item,
                reason="local assignment acquisition failed",
                exception=exc,
                cleanup=cleanup,
            )
        if (
            assignment_decision.disposition
            is not ResourceAssignmentDisposition.ASSIGNED
        ):
            cleanup = self._cleanup_pre_start(
                admission=admission,
                assignment=None,
                code="local_assignment_not_started",
            )
            if cleanup["pending"]:
                return self._pre_start_cleanup_result(
                    item,
                    reason="local assignment cleanup pending",
                    exception=None,
                    cleanup=cleanup,
                )
            if (
                assignment_decision.disposition
                is ResourceAssignmentDisposition.DEFERRED
            ):
                return QueueDispatchResult(
                    disposition=QueueDispatchDisposition.NOT_STARTED,
                    reason=assignment_decision.reason_code
                    or "resource_assignment.capacity_unavailable",
                    evidence={"local_process_started": False},
                    non_start_cause=QueueDispatchNonStartCause.CAPACITY,
                    pre_start_cleanup_status=QueuePreStartCleanupStatus.CONFIRMED,
                )
            return QueueDispatchResult(
                disposition=QueueDispatchDisposition.NOT_STARTED,
                reason=assignment_decision.reason_code or "resource assignment failed",
                evidence={"local_process_started": False},
                non_start_cause=QueueDispatchNonStartCause.INTERNAL,
                pre_start_cleanup_status=QueuePreStartCleanupStatus.CONFIRMED,
            )
        assignment = assignment_decision.assignment
        assert assignment is not None
        try:
            environment = _merge_assignment_environment(command.env, assignment)
            stdout_path, stderr_path = self._prepare_log_paths(item)
            assignment_slots = _assignment_evidence_slots(assignment)
        except Exception as exc:  # noqa: BLE001
            cleanup = self._cleanup_pre_start(
                admission=admission,
                assignment=assignment,
                code="local_assignment_launch_rejected",
            )
            return self._pre_start_cleanup_result(
                item,
                reason="local assignment launch preparation failed",
                exception=exc,
                cleanup=cleanup,
                non_start_cause=QueueDispatchNonStartCause.INVALID_OR_UNSUPPORTED,
            )
        try:
            process = self._start_process(
                command.argv,
                cwd=command.cwd,
                env=environment,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
        except Exception as exc:
            cleanup = self._cleanup_pre_start(
                admission=admission,
                assignment=assignment,
                code="local_process_start_failed",
            )
            return self._pre_start_cleanup_result(
                item,
                reason="local process start failed",
                exception=exc,
                cleanup=cleanup,
                start_uncertain=True,
            )
        handle_id = f"local:{item.queue_item_id}:{item.dispatch_attempt}:{process.pid}"
        next_renew_at, safety_deadline_at = _lease_maintenance_times(
            admission, self.lease_ttl_seconds
        )
        assignment_safety_deadline_at = _assignment_safety_deadline(
            assignment, self.lease_ttl_seconds
        )
        self._active[handle_id] = _ActiveLocalDispatch(
            process=process,
            admission=admission,
            assignment=assignment,
            next_renew_at=next_renew_at,
            safety_deadline_at=safety_deadline_at,
            assignment_safety_deadline_at=assignment_safety_deadline_at,
        )
        return QueueDispatchResult(
            disposition=QueueDispatchDisposition.STARTED,
            handle_id=handle_id,
            status=QueueItemStatus.DISPATCHED,
            reason="local process dispatched",
            evidence={
                "managed_local": _managed_local_evidence(
                    owner_id=self.owner_id,
                    session_id=self.session_id,
                    process=process,
                    admission=admission,
                    dispatched_at=self._clock(),
                    assignment=assignment,
                    assignment_slots=assignment_slots,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    log_root=self.log_directory,
                ),
            },
            next_maintenance_at=_earliest_timestamp(
                next_renew_at, assignment.next_maintenance_at
            ),
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
            if active.termination_requested:
                active.process.kill()
                returncode = active.process.poll()
                if returncode is None:
                    return QueueDispatchInspection(
                        status=QueueItemStatus.DISPATCHED,
                        reason="local process termination pending",
                        evidence={
                            "handle_id": handle_id,
                            "pid": active.process.pid,
                            "pgid": active.process.pgid,
                        },
                        terminal=False,
                        degraded=True,
                        next_maintenance_at=self._clock(),
                    )
            else:
                renewal = self._renew_if_due(active)
                if renewal is not None:
                    return renewal
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
                next_maintenance_at=_earliest_timestamp(
                    active.next_renew_at, active.assignment.next_maintenance_at
                ),
            )
        cleanup = self._cleanup_active(active, code="local_process_completed")
        if cleanup["pending"]:
            return QueueDispatchInspection(
                status=QueueItemStatus.DISPATCHED,
                reason="local resource release pending",
                evidence=cleanup["evidence"],
                terminal=False,
                degraded=True,
                next_maintenance_at=self._clock(),
            )
        self._active.pop(handle_id, None)
        if active.cancellation_requested:
            status = QueueItemStatus.CANCELLED
            reason = "local process cancelled"
        else:
            status = (
                QueueItemStatus.SUCCEEDED if returncode == 0 else QueueItemStatus.FAILED
            )
            reason = (
                "local process succeeded" if returncode == 0 else "local process failed"
            )
        evidence: dict[str, PlainData] = {
            "handle_id": handle_id,
            "pid": active.process.pid,
            "pgid": active.process.pgid,
            "returncode": returncode,
            "released_resource_leases": cleanup["admission_released"],
            "released_assignment_leases": cleanup["assignment_released"],
        }
        evidence.update(cleanup["evidence"])
        return QueueDispatchInspection(
            status=status,
            reason=reason,
            evidence=evidence,
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
        active = self._active.get(handle_id)
        if active is None:
            return QueueDispatchCancellation(
                reason=reason,
                evidence={
                    "handle_id": handle_id,
                    "recovery_needed": True,
                    "resource_leases_released": False,
                    "exit_observed": False,
                },
            )
        active.cancellation_requested = True
        returncode = active.process.poll()
        if returncode is None:
            active.process.terminate()
            # The runner is the sole source of process-exit truth.  Keep the
            # leases when it cannot yet confirm exit rather than making them reusable.
            if active.process.poll() is None:
                active.termination_requested = True
                self._active[handle_id] = active
                return QueueDispatchCancellation(
                    reason=reason,
                    evidence={
                        "handle_id": handle_id,
                        "pid": active.process.pid,
                        "pgid": active.process.pgid,
                        "requested_by": requested_by,
                        "terminated_process_group": True,
                        "exit_observed": False,
                        "released_resource_leases": False,
                    },
                )
        cleanup = self._cleanup_active(active, code="local_process_cancelled")
        if cleanup["pending"]:
            return QueueDispatchCancellation(
                reason=reason,
                evidence={
                    "handle_id": handle_id,
                    "pid": active.process.pid,
                    "pgid": active.process.pgid,
                    "requested_by": requested_by,
                    # Keep the queue item reconcilable until every owned
                    # layer has been released, even though process exit is
                    # already known.
                    "exit_observed": False,
                    "released_resource_leases": False,
                    **cleanup["evidence"],
                },
            )
        self._active.pop(handle_id, None)
        evidence: dict[str, PlainData] = {
            "handle_id": handle_id,
            "pid": active.process.pid,
            "pgid": active.process.pgid,
            "requested_by": requested_by,
            "returncode": returncode,
            "terminated_process_group": returncode is None,
            "exit_observed": True,
            "released_resource_leases": cleanup["admission_released"],
            "released_assignment_leases": cleanup["assignment_released"],
        }
        evidence.update(cleanup["evidence"])
        return QueueDispatchCancellation(
            reason=reason,
            evidence=evidence,
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
        reason = LifecycleReason(
            code=code,
            message=f"released local queue resource admission for {admission.request.run_uri}",
        )
        released: list[PlainData] = []
        ownership_error: CoordinationStoreError | None = None
        retryable_error: Exception | None = None
        for record in admission.leases:
            try:
                self.coordination_store.release_lease(
                    record.lease.lease_id,
                    owner_id=record.lease.owner_id,
                    fencing_token=record.lease.fencing_token,
                    reason=reason,
                )
                released.append(
                    {
                        "resource_key": record.resource_key,
                        "lease_id": record.lease.lease_id,
                        "amount": record.amount,
                        "released": True,
                    }
                )
            except CoordinationStoreError as exc:
                if exc.kind is CoordinationFailureKind.OWNERSHIP_LOST:
                    if ownership_error is None:
                        ownership_error = exc
                elif retryable_error is None:
                    retryable_error = exc
            except Exception as exc:  # noqa: BLE001
                if retryable_error is None:
                    retryable_error = exc
        if retryable_error is not None:
            raise retryable_error
        if ownership_error is not None:
            raise ownership_error
        return released

    def _release_assignment(
        self,
        assignment: ResourceAssignment,
        *,
        code: str,
    ) -> list[PlainData]:
        reason = LifecycleReason(code=code, message="released local queue assignment")
        self.assignment_provider.release(assignment, reason=reason)
        return [
            {
                "resource_key": lease.resource_key,
                "lease_id": lease.lease.lease_id,
                "released": True,
            }
            for lease in assignment.leases
        ]

    def _cleanup_pre_start(
        self,
        *,
        admission: ResourceAdmissionDecision,
        assignment: ResourceAssignment | None,
        code: str,
    ) -> _CleanupResult:
        """Try every owned layer, preserving uncertainty without short-circuiting."""
        active = _ActiveLocalDispatch(
            process=cast(LocalProcess, None),
            admission=admission,
            assignment=assignment
            or ResourceAssignment(provider_name="no-op", live_token=None, leases=()),
            next_renew_at=None,
            safety_deadline_at=None,
            assignment_safety_deadline_at=None,
            assignment_released=assignment is None,
        )
        return self._cleanup_active(active, code=code)

    def _pre_start_cleanup_result(
        self,
        item: QueueItem,
        *,
        reason: str,
        exception: Exception | None,
        cleanup: _CleanupResult,
        start_uncertain: bool = False,
        non_start_cause: QueueDispatchNonStartCause = QueueDispatchNonStartCause.INTERNAL,
    ) -> QueueDispatchResult:
        pending = bool(cleanup["pending"])
        evidence: dict[str, PlainData] = {
            "local_process_started": False,
            "released_resource_leases": cleanup["admission_released"],
            "released_assignment_leases": cleanup["assignment_released"],
        }
        if exception is not None:
            evidence["exception_type"] = type(exception).__name__
        evidence.update(cleanup["evidence"])
        if start_uncertain:
            return QueueDispatchResult(
                disposition=QueueDispatchDisposition.START_UNCERTAIN,
                reason="local.process_start_exception",
                evidence=evidence,
            )
        return QueueDispatchResult(
            disposition=QueueDispatchDisposition.NOT_STARTED,
            reason=reason,
            evidence=evidence,
            non_start_cause=non_start_cause,
            pre_start_cleanup_status=(
                QueuePreStartCleanupStatus.UNCERTAIN
                if pending
                else QueuePreStartCleanupStatus.CONFIRMED
            ),
        )

    def _cleanup_active(
        self, active: _ActiveLocalDispatch, *, code: str
    ) -> _CleanupResult:
        """Release assignment then scalar admission, retrying only unfinished layers."""
        evidence: dict[str, PlainData] = {}
        assignment_released: list[PlainData] = []
        admission_released: list[PlainData] = []
        pending = False
        for layer in ("assignment", "admission"):
            if layer == "assignment":
                if active.assignment_released:
                    continue
            else:
                if active.admission_released:
                    continue
            try:
                released = (
                    self._release_assignment(active.assignment, code=code)
                    if layer == "assignment"
                    else self._release_admission(active.admission, code=code)
                )
            except CoordinationStoreError as exc:
                if exc.kind is CoordinationFailureKind.OWNERSHIP_LOST:
                    if layer == "assignment":
                        active.assignment_released = True
                    else:
                        active.admission_released = True
                    evidence.setdefault("release_failure_kind", exc.kind.value)
                else:
                    pending = True
                    evidence.setdefault("release_failure_kind", exc.kind.value)
                continue
            except Exception as exc:  # noqa: BLE001
                pending = True
                evidence.setdefault("release_failure_kind", "internal")
                evidence.setdefault("release_exception_type", type(exc).__name__)
                continue
            if layer == "assignment":
                active.assignment_released = True
                assignment_released = released
            else:
                active.admission_released = True
                admission_released = released
        return {
            "pending": pending,
            "assignment_released": assignment_released,
            "admission_released": admission_released,
            "evidence": evidence,
        }

    def _prepare_log_paths(self, item: QueueItem) -> tuple[Path, Path]:
        # Item ids and attempts are already validated queue identities; the
        # session makes handles from restarted controllers distinct on disk.
        attempt = f"{item.queue_item_id}-{item.dispatch_attempt}-{self.session_id}"
        root = self.log_directory / item.pool_name
        root.mkdir(parents=True, exist_ok=True)
        stdout_path = root / f"{attempt}.stdout.log"
        stderr_path = root / f"{attempt}.stderr.log"
        stdout_path.touch(exist_ok=False)
        try:
            stderr_path.touch(exist_ok=False)
        except Exception:
            stdout_path.unlink(missing_ok=True)
            raise
        return stdout_path, stderr_path

    def _start_process(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None,
        env: Mapping[str, str] | None,
        stdout_path: Path,
        stderr_path: Path,
    ) -> LocalProcess:
        # Existing injected runners predate the log-path seam.  They remain
        # usable (and files are still reserved), while built-in subprocess
        # dispatch always receives the paths.
        parameters = inspect.signature(self.process_runner.start).parameters.values()
        supports_logs = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters
        ) or {
            "stdout_path",
            "stderr_path",
        }.issubset(inspect.signature(self.process_runner.start).parameters)
        if supports_logs:
            log_runner = cast(_LogLocalProcessRunner, self.process_runner)
            return log_runner.start(
                argv, cwd=cwd, env=env, stdout_path=stdout_path, stderr_path=stderr_path
            )
        return self.process_runner.start(argv, cwd=cwd, env=env)

    def _renew_if_due(
        self, active: _ActiveLocalDispatch
    ) -> QueueDispatchInspection | None:
        now = parse_timestamp(self._clock())
        scalar_due = active.next_renew_at is not None and now >= parse_timestamp(
            active.next_renew_at
        )
        assignment_due = (
            active.assignment.next_maintenance_at is not None
            and now >= parse_timestamp(active.assignment.next_maintenance_at)
        )
        if not scalar_due and not assignment_due:
            return None
        failures: list[tuple[str, Exception]] = []
        if scalar_due:
            try:
                renewed = tuple(
                    self.coordination_store.renew_lease(
                        lease.lease.lease_id,
                        owner_id=lease.lease.owner_id,
                        fencing_token=lease.lease.fencing_token,
                        lease_ttl_seconds=self.lease_ttl_seconds,
                    )
                    for lease in active.admission.leases
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(("scalar", exc))
            else:
                active.admission = ResourceAdmissionDecision(
                    status=ResourceAdmissionStatus.ADMITTED,
                    request=active.admission.request,
                    leases=tuple(
                        replace_resource_lease(old, new)
                        for old, new in zip(
                            active.admission.leases, renewed, strict=True
                        )
                    ),
                )
                (
                    active.next_renew_at,
                    active.safety_deadline_at,
                ) = _lease_maintenance_times(active.admission, self.lease_ttl_seconds)
        if assignment_due:
            try:
                renewed_assignment = self.assignment_provider.renew(active.assignment)
                if not isinstance(renewed_assignment, ResourceAssignment):
                    raise QueueServiceError(
                        "assignment renewal must return a ResourceAssignment"
                    )
            except Exception as exc:  # noqa: BLE001
                failures.append(("assignment", exc))
            else:
                active.assignment = renewed_assignment
                active.assignment_safety_deadline_at = _assignment_safety_deadline(
                    renewed_assignment, self.lease_ttl_seconds
                )
        if failures:
            failed_layers = {layer for layer, _error in failures}
            failed_deadlines = [
                active.safety_deadline_at
                if layer == "scalar"
                else active.assignment_safety_deadline_at
                for layer in failed_layers
            ]
            ownership_error = next(
                (
                    error
                    for _layer, error in failures
                    if isinstance(error, CoordinationStoreError)
                    and error.kind is CoordinationFailureKind.OWNERSHIP_LOST
                ),
                None,
            )
            if ownership_error is not None or _deadline_reached(now, *failed_deadlines):
                active.process.terminate()
                active.termination_requested = True
            selected_error = ownership_error or failures[0][1]
            evidence: dict[str, PlainData]
            if isinstance(selected_error, CoordinationStoreError):
                evidence = {"renewal_failure_kind": selected_error.kind.value}
            else:
                evidence = {
                    "renewal_failure_kind": "internal",
                    "exception_type": type(selected_error).__name__,
                }
            retry_times = list(failed_deadlines)
            if "scalar" not in failed_layers:
                retry_times.append(active.next_renew_at)
            if "assignment" not in failed_layers:
                retry_times.append(active.assignment.next_maintenance_at)
            return QueueDispatchInspection(
                status=QueueItemStatus.DISPATCHED,
                reason="local managed lease renewal failed",
                evidence=evidence,
                terminal=False,
                degraded=True,
                next_maintenance_at=_earliest_timestamp(*retry_times),
            )
        return None


def _dispatch_handle_id(item: QueueItem) -> str:
    if item.dispatch_handle is None:
        raise QueueServiceError("local item has no dispatch handle")
    return item.dispatch_handle.handle_id


def _lease_maintenance_times(
    admission: ResourceAdmissionDecision, ttl_seconds: int
) -> tuple[str | None, str | None]:
    if not admission.leases:
        return None, None
    renewed_at = min(
        parse_timestamp(record.lease.renewed_at) for record in admission.leases
    )
    return (
        utc_timestamp(renewed_at + timedelta(seconds=ttl_seconds * 0.5)),
        utc_timestamp(renewed_at + timedelta(seconds=ttl_seconds * 0.8)),
    )


def _assignment_safety_deadline(
    assignment: ResourceAssignment, ttl_seconds: int
) -> str | None:
    if not assignment.leases:
        return None
    renewed_at = min(
        parse_timestamp(record.lease.renewed_at) for record in assignment.leases
    )
    return utc_timestamp(renewed_at + timedelta(seconds=ttl_seconds * 0.8))


def _earliest_timestamp(*values: str | None) -> str | None:
    timestamps = [value for value in values if value is not None]
    return min(timestamps, key=parse_timestamp) if timestamps else None


def _deadline_reached(now, *deadlines: str | None) -> bool:  # noqa: ANN001
    return any(
        deadline is not None and now >= parse_timestamp(deadline)
        for deadline in deadlines
    )


def replace_resource_lease(record, lease):  # noqa: ANN001, ANN201
    """Keep the resource identity while replacing its renewed lease record."""
    return replace(record, lease=lease)


def _managed_local_evidence(
    *,
    owner_id: str,
    session_id: str,
    process: LocalProcess,
    admission: ResourceAdmissionDecision,
    dispatched_at: str,
    assignment: ResourceAssignment,
    assignment_slots: list[PlainData],
    stdout_path: Path,
    stderr_path: Path,
    log_root: Path,
) -> dict[str, PlainData]:
    return {
        "schema_version": 1,
        "owner_id": owner_id,
        "session_id": session_id,
        "pid": process.pid,
        "pgid": process.pgid,
        "dispatched_at": dispatched_at,
        "scalar_leases": [
            {
                "resource_key": lease.resource_key,
                "lease_id": lease.lease.lease_id,
                "expires_at": lease.lease.expires_at,
            }
            for lease in admission.leases
        ],
        "assignment": {
            "provider_name": assignment.provider_name,
            "slots": assignment_slots,
            "next_maintenance_at": assignment.next_maintenance_at,
        },
        "logs": {
            "stdout_path": str(stdout_path.relative_to(log_root.parent)),
            "stderr_path": str(stderr_path.relative_to(log_root.parent)),
        },
    }


def _assignment_evidence_slots(assignment: ResourceAssignment) -> list[PlainData]:
    """Project the fixed durable slot allowlist before crossing subprocess."""
    safe_evidence = thaw_plain_data(assignment.safe_evidence, path="safe_evidence")
    if not isinstance(safe_evidence, Mapping) or set(safe_evidence) != {"slots"}:
        raise QueueServiceError("assignment safe evidence must contain only slots")
    raw_slots = safe_evidence["slots"]
    if not isinstance(raw_slots, list):
        raise QueueServiceError("assignment safe evidence slots must be a list")
    slots: list[PlainData] = []
    required = {"resource_name", "slot_id", "lease_id", "expires_at"}
    allowed = required | {"label"}
    leases_by_id = {
        lease.lease.lease_id: lease.lease.expires_at for lease in assignment.leases
    }
    projected_lease_ids: set[str] = set()
    for raw_slot in raw_slots:
        if (
            not isinstance(raw_slot, Mapping)
            or not required.issubset(raw_slot)
            or set(raw_slot) - allowed
        ):
            raise QueueServiceError("assignment slot evidence has an invalid shape")
        slot: dict[str, PlainData] = {}
        for name in required:
            value = raw_slot[name]
            if not isinstance(value, str) or not value:
                raise QueueServiceError(
                    "assignment slot evidence values must be strings"
                )
            slot[name] = value
        lease_id = cast(str, slot["lease_id"])
        expires_at = cast(str, slot["expires_at"])
        if lease_id in projected_lease_ids or leases_by_id.get(lease_id) != expires_at:
            raise QueueServiceError(
                "assignment slot evidence must match its live assignment lease"
            )
        parse_timestamp(expires_at)
        projected_lease_ids.add(lease_id)
        if "label" in raw_slot:
            label = raw_slot["label"]
            if not isinstance(label, str) or not label:
                raise QueueServiceError(
                    "assignment slot label must be a non-empty string"
                )
            slot["label"] = label
        slots.append(slot)
    if projected_lease_ids != set(leases_by_id):
        raise QueueServiceError("assignment slot evidence must match assignment leases")
    return slots


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


def _merge_assignment_environment(
    environment: Mapping[str, str] | None, assignment: ResourceAssignment
) -> Mapping[str, str] | None:
    result = {} if environment is None else dict(environment)
    for name, value in assignment.bindings.environment.items():
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None or "\0" in value:
            raise QueueServiceError(
                "assignment bindings must contain environment-safe names and values"
            )
        existing = result.get(name)
        if existing is not None and existing != value:
            raise QueueServiceError(
                f"assignment binding conflicts with authored environment for {name}"
            )
        result[name] = value
    return result or None


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


def _non_start_cause(
    failure_kind: CoordinationFailureKind | None,
) -> QueueDispatchNonStartCause:
    """Map authority admission facts into the queue's narrow factual vocabulary."""

    if failure_kind is CoordinationFailureKind.UNAVAILABLE:
        return QueueDispatchNonStartCause.AUTHORITY_UNAVAILABLE
    if failure_kind is CoordinationFailureKind.OWNERSHIP_LOST:
        return QueueDispatchNonStartCause.OWNERSHIP_LOST
    return QueueDispatchNonStartCause.INTERNAL


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise QueueServiceError(f"{field} must be a non-empty string")
    return value


def _plain_mapping(
    value: Mapping[str, PlainData], path: str
) -> Mapping[str, PlainData]:
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
