"""Direct native control of one Loom coordinator over Unix or authenticated HTTPS.

Queue owns control requests and durable admission state. This integration facade
adds connection selection and the diagnostic result union above that boundary.
"""

from __future__ import annotations

from pathlib import Path
from collections.abc import Mapping
from dataclasses import dataclass
import math
import time
from typing import cast

from loom.serialization import PlainData
from loom.queue.local_daemon import (
    LocalDaemonOperation,
    LocalDaemonAdmission,
    LocalDaemonAdmissionState,
    LocalDaemonAdmissionDetail,
    OperationWaitResult,
    AdmissionWaitResult,
)

from loom.diagnostics.run_inspection import (
    RunInspectionResponse,
    decode_run_inspection_response,
)
from loom.queue._coordinator_client import NativeCoordinatorClient
from loom.queue._coordinator_control import (
    CoordinatorClientError,
    CoordinatorConnectionDescription,
    control_error,
    optional_id,
)
from loom.queue._coordinator_transport import (
    HttpsControlTransport,
    UnixControlTransport,
)
from loom.queue.errors import QueueError
from loom.queue.preparation import PrepareRunRequest
from loom.queue.run import RunRequest


@dataclass(frozen=True, slots=True)
class RunObservation:
    """Native operation, latest target observations and this caller's cleanup.

    Existing services are borrowed. No service is stopped by this observer;
    cleanup records that decision separately from execution and containment.
    ``operation.state == 'applied'`` is an admission fact, not experiment success.
    """

    operation_id: str
    operation: LocalDaemonOperation | None
    admission: LocalDaemonAdmission | None
    inspection: RunInspectionResponse | None
    connection: CoordinatorConnectionDescription

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "operation_id": self.operation_id,
            "operation": None if self.operation is None else self.operation.to_dict(),
            "admission": None if self.admission is None else self.admission.to_dict(),
            "inspection": None
            if self.inspection is None
            else self.inspection.to_dict(),
            "connection": self.connection.to_dict(),
            "cleanup": {"coordinator": "borrowed"},
        }


class CoordinatorClient(NativeCoordinatorClient):
    """Lazy coordinator client; close releases I/O without cancelling submitted work."""

    @classmethod
    def from_unix_socket(
        cls, path: str | Path, *, expected_coordinator_id: str | None = None
    ) -> CoordinatorClient:
        """Select an owner-only local socket without starting or contacting a service."""
        return cls(
            UnixControlTransport(path), expected_coordinator_id=expected_coordinator_id
        )

    @classmethod
    def from_connection_file(
        cls, path: str | Path, *, expected_coordinator_id: str | None = None
    ) -> CoordinatorClient:
        """Load protected HTTPS settings; certificate use and negotiation are lazy."""
        from loom.queue.deployment import load_coordinator_connection_file

        config = load_coordinator_connection_file(path)
        try:
            selected = optional_id(expected_coordinator_id)
        except ValueError as exc:
            raise control_error("invalid_request", "connection", {}) from exc
        configured = config.expected_coordinator_id
        if configured is not None and selected is not None and configured != selected:
            raise control_error(
                "conflict",
                "connection",
                {},
                ids={
                    "configured_expected_coordinator_id": configured,
                    "expected_coordinator_id": selected,
                },
            )
        return cls(
            HttpsControlTransport(
                config.url,
                config.server_ca_path,
                config.certificate_path,
                config.private_key_path,
            ),
            expected_coordinator_id=configured if configured is not None else selected,
        )

    def observe_run(
        self,
        operation_id: str,
        *,
        wait: bool = True,
        timeout_seconds: float | None = None,
        expected_coordinator_id: str | None = None,
    ) -> RunObservation:
        """Observe an accepted run through admission and native terminal settlement.

        ``wait=False``, timeout, Ctrl-C and EOF detach with the latest references.
        A BLOCKED admission returns its native diagnostic state without claiming
        containment or success. Services are already running and remain borrowed.
        Reconnect with the returned coordinator identity and operation ID.
        """
        if not isinstance(wait, bool) or (
            timeout_seconds is not None
            and (
                isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, (int, float))
                or not math.isfinite(timeout_seconds)
                or timeout_seconds < 0
            )
        ):
            raise control_error(
                "invalid_request", "observe_run", {"operation_id": operation_id}
            )
        deadline = (
            None if timeout_seconds is None else time.monotonic() + timeout_seconds
        )
        guard = self._guard("observe_run", {"operation_id": operation_id}, expected_coordinator_id)
        if timeout_seconds == 0 and self._last_connection is not None:
            connection = self._last_connection
            if guard is not None and connection.coordinator_id != guard:
                raise control_error("conflict", "observe_run", {"operation_id": operation_id})
        else:
            connection = cast(
                CoordinatorConnectionDescription,
                self._native_call("handshake", {}, expected_coordinator_id, deadline=deadline),
            )
        owner = connection.coordinator_id
        operation = None
        admission = None
        inspection = None
        try:
            while deadline is None or time.monotonic() < deadline:
                if operation is None:
                    operation = cast(
                        LocalDaemonOperation,
                        self._native_call(
                            "operation",
                            {"operation_id": operation_id},
                            owner,
                            deadline=deadline,
                        ),
                    )
                    if operation.kind != "run":
                        raise control_error(
                            "invalid_request",
                            "observe_run",
                            {"operation_id": operation_id},
                        )
                result = cast(Mapping[str, PlainData], operation.result)
                retained = result.get("admission")
                if isinstance(retained, Mapping):
                    admission = cast(
                        LocalDaemonAdmissionDetail,
                        self._native_call(
                            "admission",
                            {"admission_id": retained["admission_id"]},
                            owner,
                            deadline=deadline,
                        ),
                    ).admission
                    inspection = self._inspect_run(admission.run_uri, owner, deadline)
                if not wait or operation.state in {"failed", "cancelled", "conflict"}:
                    break
                duration = (
                    25.0
                    if deadline is None
                    else min(25.0, max(0.0, deadline - time.monotonic()))
                )
                if admission is None:
                    observed = cast(
                        OperationWaitResult,
                        self._wait_native(
                            "wait_operation",
                            {"operation_id": operation_id},
                            duration,
                            owner,
                            terminal_deadline=deadline,
                        ),
                    )
                    operation = observed.operation
                else:
                    if admission.state in {
                        LocalDaemonAdmissionState.SUCCEEDED,
                        LocalDaemonAdmissionState.FAILED,
                        LocalDaemonAdmissionState.CANCELLED,
                        LocalDaemonAdmissionState.BLOCKED,
                    }:
                        break
                    observed_admission = cast(
                        AdmissionWaitResult,
                        self._wait_native(
                            "wait_admission",
                            {
                                "admission_id": admission.admission_id,
                                "expected_revision": admission.revision,
                            },
                            duration,
                            owner,
                            terminal_deadline=deadline,
                        ),
                    )
                    admission = observed_admission.admission
        except (KeyboardInterrupt, EOFError):
            pass
        except CoordinatorClientError as exc:
            if (
                exc.code != "deadline_exceeded"
                or deadline is None
                or time.monotonic() < deadline
            ):
                raise
        return RunObservation(
            operation_id, operation, admission, inspection, connection
        )

    def inspect_run(
        self, run_uri: str, *, expected_coordinator_id: str | None = None
    ) -> RunInspectionResponse:
        """Read a managed run's native inspection success or diagnostic failure union."""
        return self._inspect_run(run_uri, expected_coordinator_id, None)

    def _inspect_run(
        self, run_uri: str, owner: str | None, deadline: float | None
    ) -> RunInspectionResponse:
        value = self._native_call(
            "inspect_run", {"run_uri": run_uri}, owner, deadline=deadline
        )
        try:
            return decode_run_inspection_response(value)
        except (QueueError, ValueError, TypeError, KeyError, RecursionError) as exc:
            raise control_error(
                "invalid_response", "inspect_run", {"run_uri": run_uri}, dispatched=True
            ) from exc


__all__ = [
    "CoordinatorClient",
    "CoordinatorClientError",
    "CoordinatorConnectionDescription",
    "PrepareRunRequest",
    "RunRequest",
    "RunObservation",
]
