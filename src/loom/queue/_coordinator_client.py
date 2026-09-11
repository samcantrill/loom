"""Shared native client behavior behind the integration and socket adapters."""

from __future__ import annotations

from collections.abc import Mapping
import math
import time
from typing import Any, Self, cast

from loom.serialization import PlainData

from ._coordinator_control import (
    CONTROL_CAPABILITY,
    MAX_OBSERVATION_SECONDS,
    MUTATION_OPERATIONS,
    WAIT_OPERATIONS,
    CoordinatorClientError,
    CoordinatorConnectionDescription,
    control_error,
    decode_envelope,
    decode_result,
    observation_timeout,
    optional_id,
    validate_request,
)
from . import _coordinator_transport as transport_io
from ._coordinator_transport import ControlTransport
from .errors import QueueError, QueueServiceError
from .local_daemon import (
    AdmissionNotFoundError,
    AdmissionPage,
    AdmissionWaitKind,
    AdmissionWaitResult,
    AgentPage,
    AgentProjection,
    DaemonStatus,
    LocalDaemonAdmission,
    LocalDaemonAdmissionDetail,
    LocalDaemonAdmissionRequest,
    LocalDaemonOperation,
    OperationWaitResult,
)
from .preparation import PrepareRunRequest
from .run import RunRequest


class NativeCoordinatorClient:
    """One owner for control request, decode, guard and observation semantics."""

    def __init__(
        self,
        transport: ControlTransport,
        *,
        expected_coordinator_id: str | None = None,
        legacy: bool = False,
    ) -> None:
        self._transport = transport
        self._legacy = legacy
        try:
            self._expected_coordinator_id = optional_id(expected_coordinator_id)
        except ValueError as exc:
            raise control_error("invalid_request", "connection", {}) from exc

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Release local I/O resources without requesting lifecycle cancellation."""
        self._transport.close()

    def _guard(
        self, operation: str, payload: Mapping[str, PlainData], expected: object
    ) -> str | None:
        try:
            selected = optional_id(expected)
        except ValueError as exc:
            raise control_error("invalid_request", operation, payload) from exc
        default = self._expected_coordinator_id
        if default is not None and selected is not None and default != selected:
            raise control_error(
                "conflict",
                operation,
                payload,
                ids={
                    "configured_expected_coordinator_id": default,
                    "expected_coordinator_id": selected,
                },
            )
        return default if default is not None else selected

    def _exchange(
        self,
        operation: str,
        payload: Mapping[str, PlainData],
        deadline: float,
        *,
        waiting: bool,
    ) -> Mapping[str, object]:
        delay = 0.01
        while True:
            try:
                response = self._transport.call(
                    operation,
                    payload,
                    deadline,
                    legacy=self._legacy,
                    waiting=waiting,
                )
                if not self._legacy:
                    try:
                        return decode_envelope(response, operation, payload)
                    except (ValueError, TypeError, KeyError, RecursionError) as exc:
                        raise control_error(
                            "invalid_response", operation, payload, dispatched=True
                        ) from exc
                if response.get("ok") is not True:
                    diagnostic = response.get("error")
                    if diagnostic == "local_daemon_admission_not_found":
                        raise AdmissionNotFoundError(diagnostic)
                    raise QueueServiceError(
                        diagnostic
                        if isinstance(diagnostic, str)
                        else "local_daemon_request_failed"
                    )
                value = response.get("result")
                if not isinstance(value, Mapping):
                    raise QueueServiceError("local daemon returned an invalid result")
                return value
            except CoordinatorClientError as exc:
                if self._legacy:
                    if exc.code == "not_found":
                        raise AdmissionNotFoundError(
                            "local_daemon_admission_not_found"
                        ) from exc
                    if exc.code == "deadline_exceeded":
                        raise
                    raise QueueServiceError(
                        "local daemon endpoint is unavailable"
                    ) from exc
                if (
                    operation in MUTATION_OPERATIONS
                    or exc.code != "capacity_exhausted"
                ):
                    raise
                left = deadline - time.monotonic()
                if left <= 0:
                    raise
                time.sleep(min(delay, left))
                delay = min(0.1, delay * 2)
            except QueueServiceError as exc:
                if (
                    not self._legacy
                    or operation in MUTATION_OPERATIONS
                    or str(exc)
                    not in {
                        "local_daemon_wait_capacity_exhausted",
                        "local_daemon_worker_capacity_exhausted",
                    }
                ):
                    raise
                left = deadline - time.monotonic()
                if left <= 0:
                    raise
                time.sleep(min(delay, left))
                delay = min(0.1, delay * 2)

    def _native_call(
        self,
        operation: str,
        payload: Mapping[str, PlainData],
        expected: str | None = None,
        *,
        deadline: float | None = None,
        negotiate: bool = True,
        waiting: bool = False,
    ) -> Any:
        bound = time.monotonic() + transport_io.REQUEST_BUDGET_SECONDS
        if deadline is not None:
            bound = min(bound, deadline)
        guard = self._guard(operation, payload, expected)
        envelope = dict(payload)
        if guard is not None:
            envelope["expected_coordinator_id"] = guard
        try:
            validate_request(operation, envelope, legacy=self._legacy)
        except (ValueError, TypeError, QueueError) as exc:
            if self._legacy:
                raise QueueServiceError("local daemon request is invalid") from exc
            raise control_error("invalid_request", operation, envelope) from exc
        waiting = waiting or operation in WAIT_OPERATIONS
        if not self._legacy and operation != "handshake" and negotiate:
            try:
                # Separate connections renegotiate within this request's budget.
                description = self._native_call(
                    "handshake", {}, guard, deadline=bound, waiting=waiting
                )
                if operation == "start_run":
                    # Retain the owner learned before mutation even if the
                    # acceptance response disappears. Later calls stay bound.
                    self._expected_coordinator_id = description.coordinator_id
                    envelope["expected_coordinator_id"] = description.coordinator_id
            except CoordinatorClientError as exc:
                raise CoordinatorClientError(
                    exc.code,
                    boundary=exc.boundary,
                    operation=operation,
                    ids={**exc.ids, **control_error(exc.code, operation, envelope).ids},
                    evidence_refs=exc.evidence_refs,
                    mutation_outcome="not_applied"
                    if operation in MUTATION_OPERATIONS
                    else None,
                    message=str(exc),
                ) from exc
        value = self._exchange(operation, envelope, bound, waiting=waiting)
        try:
            if operation == "handshake":
                capabilities = value.get("capabilities")
                version = value.get("protocol_version")
                if (
                    isinstance(capabilities, list)
                    and CONTROL_CAPABILITY not in capabilities
                ) or (isinstance(version, str) and version != "1"):
                    raise control_error("unsupported", operation, envelope)
            return decode_result(operation, value)
        except CoordinatorClientError:
            raise
        except (QueueError, ValueError, TypeError, KeyError, RecursionError) as exc:
            if self._legacy:
                raise QueueServiceError(
                    "local daemon returned an invalid result"
                ) from exc
            raise control_error(
                "invalid_response", operation, envelope, dispatched=True
            ) from exc

    def describe_connection(
        self, *, expected_coordinator_id: str | None = None
    ) -> CoordinatorConnectionDescription:
        """Observe protocol, coordinator identity and currently enabled aliases."""
        return cast(
            CoordinatorConnectionDescription,
            self._native_call("handshake", {}, expected_coordinator_id),
        )

    def status(self, *, expected_coordinator_id: str | None = None) -> DaemonStatus:
        """Observe coordinator status without interpreting it as stage execution."""
        return cast(
            DaemonStatus, self._native_call("status", {}, expected_coordinator_id)
        )

    def admissions(
        self,
        limit: int = 20,
        cursor: str | None = None,
        *,
        expected_coordinator_id: str | None = None,
    ) -> AdmissionPage:
        """Read a native page of 1–100 admissions, defaulting to 20."""
        return cast(
            AdmissionPage,
            self._native_call(
                "admissions",
                {"limit": limit, "cursor": cursor},
                expected_coordinator_id,
            ),
        )

    def admission(
        self, admission_id: str, *, expected_coordinator_id: str | None = None
    ) -> LocalDaemonAdmissionDetail:
        """Read one admission and its non-atomic owner evidence."""
        return cast(
            LocalDaemonAdmissionDetail,
            self._native_call(
                "admission", {"admission_id": admission_id}, expected_coordinator_id
            ),
        )

    def admission_for_queue_item(
        self, queue_item_id: str, *, expected_coordinator_id: str | None = None
    ) -> LocalDaemonAdmission:
        """Resolve the caller's submission ID; later detail is another observation."""
        return cast(
            LocalDaemonAdmission,
            self._native_call(
                "admission_for_queue_item",
                {"queue_item_id": queue_item_id},
                expected_coordinator_id,
            ),
        )

    def agents(
        self,
        limit: int = 20,
        cursor: str | None = None,
        *,
        expected_coordinator_id: str | None = None,
    ) -> AgentPage:
        """Read observed agent availability without reserving capacity."""
        return cast(
            AgentPage,
            self._native_call(
                "agents", {"limit": limit, "cursor": cursor}, expected_coordinator_id
            ),
        )

    def agent(
        self, agent_id: str, *, expected_coordinator_id: str | None = None
    ) -> AgentProjection:
        """Read one native agent projection and its freshness evidence."""
        return cast(
            AgentProjection,
            self._native_call("agent", {"agent_id": agent_id}, expected_coordinator_id),
        )

    def operation(
        self, operation_id: str, *, expected_coordinator_id: str | None = None
    ) -> LocalDaemonOperation:
        """Read an operation; an observed failed operation is a successful read."""
        return cast(
            LocalDaemonOperation,
            self._native_call(
                "operation", {"operation_id": operation_id}, expected_coordinator_id
            ),
        )

    def submit(
        self,
        request: LocalDaemonAdmissionRequest,
        *,
        expected_coordinator_id: str | None = None,
    ) -> LocalDaemonAdmission:
        """Admit prepared work or explicitly retry its observed failed revision.

        Reconcile unknown outcomes with the same request. Ordinary submission
        replay observes terminal state without authorizing another attempt.
        """
        if not isinstance(request, LocalDaemonAdmissionRequest):
            raise control_error("invalid_request", "submit", {})
        return cast(
            LocalDaemonAdmission,
            self._native_call(
                "submit", {"request": request.to_dict()}, expected_coordinator_id
            ),
        )

    def prepare_run(
        self,
        request: PrepareRunRequest,
        *,
        expected_coordinator_id: str | None = None,
    ) -> LocalDaemonOperation:
        """Durably accept preparation; completion is observed separately."""
        if not isinstance(request, PrepareRunRequest):
            raise control_error("invalid_request", "prepare_run", {})
        return cast(
            LocalDaemonOperation,
            self._native_call(
                "prepare_run", {"request": request.to_dict()}, expected_coordinator_id
            ),
        )

    def start_run(
        self, request: RunRequest, *, expected_coordinator_id: str | None = None
    ) -> LocalDaemonOperation:
        """Durably accept preparation plus admission; returning detaches observation.

        Supply the same operation and queue IDs to recover an uncertain reply.
        Acceptance does not mean publication, admission, or execution has finished.
        """
        if not isinstance(request, RunRequest):
            raise control_error("invalid_request", "start_run", {})
        return cast(LocalDaemonOperation, self._native_call(
            "start_run", {"request": request.to_dict()}, expected_coordinator_id
        ))

    def cancel_run_operation(
        self, operation_id: str, *, expected_coordinator_id: str | None = None
    ) -> LocalDaemonOperation:
        """Explicitly cancel a run; wait on the returned independent control ID."""
        return cast(LocalDaemonOperation, self._native_call(
            "cancel_run_operation", {"operation_id": operation_id}, expected_coordinator_id
        ))

    def cancel_preparation(
        self,
        operation_id: str,
        *,
        expected_coordinator_id: str | None = None,
    ) -> LocalDaemonOperation:
        """Request cancellation of one preparation operation."""
        return cast(
            LocalDaemonOperation,
            self._native_call(
                "cancel_preparation", {"operation_id": operation_id}, expected_coordinator_id
            ),
        )

    def cancel(
        self, queue_item_id: str, *, expected_coordinator_id: str | None = None
    ) -> LocalDaemonAdmission:
        """Request cancellation; the returned acknowledgement is not release proof."""
        return cast(
            LocalDaemonAdmission,
            self._native_call(
                "cancel", {"queue_item_id": queue_item_id}, expected_coordinator_id
            ),
        )

    def _wait_native(
        self,
        operation: str,
        payload: Mapping[str, PlainData],
        timeout: float | None,
        expected: str | None,
        *,
        legacy: bool = False,
        terminal_deadline: float | None = None,
    ) -> Any:
        try:
            duration = observation_timeout(timeout, legacy=legacy)
        except ValueError as exc:
            if self._legacy:
                raise QueueServiceError("local daemon wait timeout is invalid") from exc
            raise control_error("invalid_request", operation, payload) from exc
        started = time.monotonic()
        observation_end = None if duration is None else started + duration
        budget_end = started + transport_io.REQUEST_BUDGET_SECONDS
        if terminal_deadline is not None:
            budget_end = min(budget_end, terminal_deadline)
        negotiate = True
        while True:
            left = (
                MAX_OBSERVATION_SECONDS
                if observation_end is None
                else max(0.0, observation_end - time.monotonic())
            )
            value = self._native_call(
                operation,
                {**payload, "timeout": min(MAX_OBSERVATION_SECONDS, left)},
                expected,
                deadline=budget_end,
                negotiate=negotiate,
                waiting=True,
            )
            negotiate = False
            if value.kind.value != "TIMEOUT" or (
                observation_end is not None and time.monotonic() >= observation_end
            ):
                return value
            if legacy and budget_end - time.monotonic() < 5.0:
                budget_end = time.monotonic() + transport_io.REQUEST_BUDGET_SECONDS
                if terminal_deadline is not None:
                    budget_end = min(budget_end, terminal_deadline)
                negotiate = True

    def wait_operation(
        self,
        operation_id: str,
        timeout_seconds: float = 25,
        *,
        expected_coordinator_id: str | None = None,
    ) -> OperationWaitResult:
        """Observe for 0–25 seconds; TIMEOUT does not cancel durable work."""
        return cast(
            OperationWaitResult,
            self._wait_native(
                "wait_operation",
                {"operation_id": operation_id},
                timeout_seconds,
                expected_coordinator_id,
            ),
        )

    def wait_admission(
        self,
        admission_id: str,
        expected_revision: int,
        timeout_seconds: float = 25,
        *,
        expected_coordinator_id: str | None = None,
    ) -> AdmissionWaitResult:
        """Observe one revision for 0–25 seconds, returning change/terminal/timeout."""
        return cast(
            AdmissionWaitResult,
            self._wait_native(
                "wait_admission",
                {"admission_id": admission_id, "expected_revision": expected_revision},
                timeout_seconds,
                expected_coordinator_id,
            ),
        )

    def wait(
        self,
        queue_item_id: str,
        timeout_seconds: float | None = None,
        *,
        expected_coordinator_id: str | None = None,
    ) -> LocalDaemonAdmission:
        """Explicitly wait for terminal admission; None allows unlimited renewal."""
        if timeout_seconds is not None and (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds < 0
        ):
            raise control_error(
                "invalid_request", "wait", {"queue_item_id": queue_item_id}
            )
        deadline = (
            None if timeout_seconds is None else time.monotonic() + timeout_seconds
        )
        # Zero still makes one nonblocking native observation.
        call_deadline = None if timeout_seconds == 0 else deadline
        try:
            admission = cast(
                LocalDaemonAdmission,
                self._native_call(
                    "admission_for_queue_item",
                    {"queue_item_id": queue_item_id},
                    expected_coordinator_id,
                    deadline=call_deadline,
                ),
            )
            while True:
                duration = (
                    MAX_OBSERVATION_SECONDS
                    if deadline is None
                    else min(
                        MAX_OBSERVATION_SECONDS, max(0.0, deadline - time.monotonic())
                    )
                )
                observed = cast(
                    AdmissionWaitResult,
                    self._wait_native(
                        "wait_admission",
                        {
                            "admission_id": admission.admission_id,
                            "expected_revision": admission.revision,
                        },
                        duration,
                        expected_coordinator_id,
                        terminal_deadline=call_deadline,
                    ),
                )
                admission = observed.admission
                if observed.kind is AdmissionWaitKind.TERMINAL:
                    return admission
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError(
                        "managed local admission did not reach terminal state"
                    )
        except CoordinatorClientError as exc:
            if (
                exc.code == "deadline_exceeded"
                and deadline is not None
                and time.monotonic() >= deadline
            ):
                raise TimeoutError(
                    "managed local admission did not reach terminal state"
                ) from exc
            raise
