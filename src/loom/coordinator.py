"""Direct native control of one Loom coordinator over Unix or authenticated HTTPS.

Queue owns control requests and durable admission state. This integration facade
adds connection selection and the diagnostic result union above that boundary.
"""

from __future__ import annotations

from pathlib import Path
from collections.abc import Mapping, Iterator
from dataclasses import dataclass
import math
import time
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from loom.diagnostics.run_explanation import RunExplanation

from loom.serialization import PlainData
from loom.runs.context import RunAnnotations, RunContext
from loom.runs.annotations import RunNote, RunNotePage
from loom.runs.query import RunQuery, SubmissionQuery, JobQuery, ManagedScope
from loom.runs._query_page import QueryPage
from loom.runs.outputs import OutputLocator, OutputSelection
from loom.runs.lineage import LineageQuery
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
from loom.queue.operations import OperatorObservation
from loom.queue.agent_sessions import AgentControl


@dataclass(frozen=True, slots=True)
class RunObservation:
    """Native operation, latest target observations and this caller's cleanup.

    Existing services are borrowed. No service is stopped by this observer;
    cleanup records that decision separately from execution and containment.
    ``operation.state == 'applied'`` is an admission fact, not experiment success.
    ``detail`` retains the existing owner join for pure explanations; the
    established observation serialization is unchanged.
    """

    operation_id: str
    operation: LocalDaemonOperation | None
    admission: LocalDaemonAdmission | None
    inspection: RunInspectionResponse | None
    connection: CoordinatorConnectionDescription
    detail: LocalDaemonAdmissionDetail | None = None

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

    def cancel_run_operation(
        self, operation_id: str, *, expected_coordinator_id: str | None = None,
        deadline: float | None = None,
    ) -> LocalDaemonOperation:
        """Return the native cancellation control operation within an absolute deadline.

        Wait on its returned ID for child/target settlement. After binding this
        cancels the shared target for all observers; detaching remains separate.
        """
        return cast(LocalDaemonOperation, self._native_call(
            "cancel_run_operation", {"operation_id": operation_id},
            expected_coordinator_id, deadline=deadline,
        ))

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
        detail = None
        try:
            while deadline is None or time.monotonic() < deadline:
                for snapshot in self._run_observation_steps(
                    operation_id, connection, deadline=deadline, operation=operation,
                ):
                    operation = snapshot.operation
                    admission = snapshot.admission or admission
                    inspection = snapshot.inspection or inspection
                    detail = snapshot.detail or detail
                assert operation is not None
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
            operation_id, operation, admission, inspection, connection, detail
        )

    def _run_observation_steps(
        self, operation_id: str, connection: CoordinatorConnectionDescription, *,
        deadline: float | None, operation: LocalDaemonOperation | None = None,
    ) -> Iterator[RunObservation]:
        """Retain each completed read without consuming the caller's interruption."""
        owner = connection.coordinator_id
        if operation is None:
            operation = cast(LocalDaemonOperation, self._native_call(
                "operation", {"operation_id": operation_id}, owner, deadline=deadline,
            ))
            if operation.kind != "run":
                raise control_error("invalid_request", "observe_run", {"operation_id": operation_id})
        result = cast(Mapping[str, PlainData], operation.result)
        retained = result.get("admission")
        admission = None
        inspection = None
        yield RunObservation(operation_id, operation, None, None, connection)
        if isinstance(retained, Mapping):
            detail = cast(LocalDaemonAdmissionDetail, self._native_call(
                "admission", {"admission_id": retained["admission_id"]}, owner, deadline=deadline,
            ))
            admission = detail.admission
            yield RunObservation(operation_id, operation, admission, None, connection, detail)
            inspection = self._inspect_run(admission.run_uri, owner, deadline)
            yield RunObservation(operation_id, operation, admission, inspection, connection, detail)

    def explain_run(
        self, operation_id: str, *, timeout_seconds: float = 25.0,
        expected_coordinator_id: str | None = None, deployment: str | None = None,
    ) -> "RunExplanation":
        """Bounded connect-only explanation; retain completed reads on owner loss.

        Unknown operations stay ``not_found``. Authentication, identity and codec
        errors propagate. A later unavailable owner cannot erase earlier facts.
        """
        from loom.diagnostics.run_explanation import explain_run

        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise control_error("invalid_request", "explain_run", {"operation_id": operation_id})
        deadline = time.monotonic() + timeout_seconds
        observation = None
        error_code = None
        try:
            connection = self._native_call("handshake", {}, expected_coordinator_id, deadline=deadline)
            for snapshot in self._run_observation_steps(operation_id, connection, deadline=deadline):
                observation = snapshot
        except CoordinatorClientError as exc:
            if exc.code not in {"unavailable", "deadline_exceeded", "not_found", "maintenance_in_progress"}:
                raise
            error_code = exc.code
        return explain_run(
            None if observation is None else observation.inspection,
            observation=observation, operation_id=operation_id, deployment=deployment,
            error_code=error_code,
        )

    def get_run_context(self, run_uri: str, *, expected_coordinator_id: str | None = None) -> RunContext:
        """Read original intent, current annotations and native evidence without execution."""
        return RunContext.from_dict(self._native_call(
            "get_run_context", {"run_uri": run_uri}, expected_coordinator_id))

    def describe_artifact(self, locator: OutputLocator, *, scope: Any = None, cursor: int = 0, limit: int = 100, declaration: str | None = None, expected_coordinator_id: str | None = None, deadline: float | None = None) -> dict[str, Any]:
        """Describe a complete authorized declaration, with bounded member pages.

        Pass its declaration identity on subsequent pages and chunk reads.
        Original checksums and unverified legacy content are distinguished.
        An optional absolute monotonic deadline bounds native I/O.
        """
        return self._artifact_request("describe_artifact", locator, scope, {"cursor": cursor, "limit": limit, "declaration": declaration}, expected_coordinator_id, deadline=deadline)

    def read_artifact_chunk(self, locator: OutputLocator, *, declaration: str, member: str, offset: int, length: int = 256 * 1024, scope: Any = None, expected_coordinator_id: str | None = None, deadline: float | None = None) -> dict[str, Any]:
        """Read at most 256 KiB at a byte offset; data is base64 in the response.

        Repeating the exact request is side-effect free. Membership, authorization,
        and declaration identity are checked again; no current-head substitution.
        An optional absolute monotonic deadline bounds native I/O.
        """
        return self._artifact_request("read_artifact_chunk", locator, scope, {"declaration": declaration, "member": member, "offset": offset, "length": length}, expected_coordinator_id, deadline=deadline)

    def read_artifact(self, locator: OutputLocator, *, format: str = "text", limit: int = 256 * 1024, member: str | None = None, scope: Any = None, expected_coordinator_id: str | None = None) -> dict[str, Any]:
        """Preview UTF-8 text, whole JSON, or base64 bytes, bounded by raw bytes.

        Defaults to the declared primary. Text prefixes preserve UTF-8 boundaries;
        oversized JSON returns too_large. Recorded codecs are never executed.
        """
        return self._artifact_request("read_artifact", locator, scope, {"format": format, "limit": limit, "member": member}, expected_coordinator_id)

    def _artifact_request(self, operation: str, locator: OutputLocator, scope: Any, options: dict[str, Any], expected: str | None, *, deadline: float | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"locator": locator.to_dict(), "scope": scope.to_dict() if hasattr(scope, "to_dict") else scope or {"kind": "managed"}, **options}
        return cast(dict[str, Any], self._native_call(operation, payload, expected, deadline=deadline))

    def fetch_artifacts(self, selections: Any, destination: str | Path, *, scope: Any = None, expected_coordinator_id: str | None = None, deadline: float | None = None) -> dict[str, Any]:
        """Fetch complete declarations into new directories on this client's host.

        Preserve input associations and outcomes in order, deduplicating bytes.
        Complete means every input was processed, not that each succeeded. Existing
        directories are never replaced. Linux atomic publication is required.
        An optional absolute monotonic deadline is shared by all native calls.
        Expiry fails unfinished items, cleans owned temporary files and prevents
        further publication; previously published items remain successful.
        """
        from loom._artifact_fetch import fetch_artifacts
        return fetch_artifacts(self, selections, destination, scope=scope, expected_coordinator_id=expected_coordinator_id, deadline=deadline)

    def select_outputs(self, selection: OutputSelection, *, expected_coordinator_id: str | None = None) -> QueryPage:
        """Select exact published metadata, preserving reuse and per-selector outcomes."""
        return cast(QueryPage, self._native_call("select_outputs", {"selection": selection.to_dict()}, expected_coordinator_id))

    def list_output_commits(self, selection: OutputSelection, *, expected_coordinator_id: str | None = None) -> QueryPage:
        """Page retained commits with their matching output facts and associations."""
        return cast(QueryPage, self._native_call("list_output_commits", {"selection": selection.to_dict()}, expected_coordinator_id))

    def trace_lineage(self, query: LineageQuery, *, expected_coordinator_id: str | None = None) -> QueryPage:
        """Trace exact assigned inputs, acknowledged starts and reuse within scope."""
        return cast(QueryPage, self._native_call("trace_lineage", {"query": query.to_dict()}, expected_coordinator_id))

    def search_runs(self, query: RunQuery, *, expected_coordinator_id: str | None = None) -> QueryPage:
        """Search one explicit scope, preserving live continuation and coverage."""
        return cast(QueryPage, self._native_call("search_runs", {"query": query.to_dict()}, expected_coordinator_id))

    def search_submissions(self, query: SubmissionQuery, *, expected_coordinator_id: str | None = None) -> QueryPage:
        """Search original requests, including failed and not-yet-bound operations."""
        return cast(QueryPage, self._native_call("search_submissions", {"query": query.to_dict()}, expected_coordinator_id))

    def search_jobs(self, query: JobQuery, *, expected_coordinator_id: str | None = None) -> QueryPage:
        """Search admissions with their native run, queue and assignment associations."""
        return cast(QueryPage, self._native_call("search_jobs", {"query": query.to_dict()}, expected_coordinator_id))

    def query_fields(self, entity: str = "runs", *, expected_coordinator_id: str | None = None) -> Mapping[str, PlainData]:
        """Discover the finite supported fields, operators, scopes and limits."""
        return cast(Mapping[str, PlainData], self._native_call("query_fields", {"entity": entity}, expected_coordinator_id))

    def tag_keys(self, scope: object = ManagedScope(), *, limit: int = 50, cursor: str | None = None,
                 expected_coordinator_id: str | None = None) -> QueryPage:
        """Read bounded distinct current label keys in the selected scope."""
        from loom.runs.query import _plain
        return cast(QueryPage, self._native_call("tag_keys", {"scope": _plain(scope), "limit": limit, "cursor": cursor}, expected_coordinator_id))

    def tag_values(self, scope: object, key: str, *, limit: int = 50, cursor: str | None = None,
                   expected_coordinator_id: str | None = None) -> QueryPage:
        """Read bounded distinct values for one literal label key."""
        from loom.runs.query import _plain
        return cast(QueryPage, self._native_call("tag_values", {"scope": _plain(scope), "key": key, "limit": limit, "cursor": cursor}, expected_coordinator_id))

    def patch_run_annotations(self, run_uri: str, *, mutation_id: str,
                              expected_revision: int,
                              set_tags: Mapping[str, str] | None = None,
                              remove_tags: tuple[str, ...] = (),
                              set_metadata: Mapping[str, PlainData] | None = None,
                              remove_metadata: tuple[str, ...] = (),
                              expected_coordinator_id: str | None = None,
                              **description_change: PlainData) -> RunAnnotations:
        """Apply a CAS patch. Omit description to preserve it; pass null to clear.

        Replay an uncertain response with the same run, mutation ID and request.
        A conflict reports the current revision; deliberately rebase with a new ID.
        IDs are scoped to this run and authenticated principal, across both writes.
        """
        patch: dict[str, PlainData] = {"expected_revision": expected_revision,
            "set_tags": dict(set_tags or {}), "remove_tags": list(remove_tags),
            "set_metadata": dict(set_metadata or {}), "remove_metadata": list(remove_metadata),
            **description_change}
        return cast(RunAnnotations, self._native_call("patch_run_annotations",
            {"run_uri": run_uri, "mutation_id": mutation_id, "patch": patch}, expected_coordinator_id))

    def append_run_note(self, run_uri: str, *, mutation_id: str, text: str,
                        expected_coordinator_id: str | None = None) -> RunNote:
        """Append one observation with native author/time; retry the same ID/request."""
        return cast(RunNote, self._native_call("append_run_note",
            {"run_uri": run_uri, "mutation_id": mutation_id, "text": text}, expected_coordinator_id))

    def list_run_notes(self, run_uri: str, *, limit: int = 50, cursor: str | None = None,
                       expected_coordinator_id: str | None = None) -> RunNotePage:
        """Read up to 50 notes in native UTC time/ID order, legacy unknown times first."""
        return cast(RunNotePage, self._native_call("list_run_notes",
            {"run_uri": run_uri, "limit": limit, "cursor": cursor}, expected_coordinator_id))

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
    "CoordinatorOperatorClient",
    "CoordinatorClient",
    "CoordinatorClientError",
    "CoordinatorConnectionDescription",
    "PrepareRunRequest",
    "RunRequest",
    "RunObservation",
]


class CoordinatorOperatorClient(NativeCoordinatorClient):
    """Explicit operator-role connection; ordinary client credentials cannot use it.

    Controls require an expected coordinator ID and retain native operation and
    intent identity. A transport timeout reports unknown, never non-application.
    """

    _handshake_operation = "operator_handshake"
    _retained_status: OperatorObservation | None = None

    @classmethod
    def from_unix_socket(cls, path: str | Path, *, expected_coordinator_id: str | None = None) -> CoordinatorOperatorClient:
        return cls(UnixControlTransport(path), expected_coordinator_id=expected_coordinator_id)

    @classmethod
    def from_connection_file(cls, path: str | Path, *, expected_coordinator_id: str | None = None) -> CoordinatorOperatorClient:
        from loom.queue.deployment import load_coordinator_connection_file
        config = load_coordinator_connection_file(path)
        try:
            selected = optional_id(expected_coordinator_id)
        except ValueError as exc:
            raise control_error("invalid_request", "connection", {}) from exc
        if selected is not None and config.expected_coordinator_id not in {None, selected}:
            raise control_error("conflict", "connection", {})
        return cls(HttpsControlTransport(config.url, config.server_ca_path, config.certificate_path, config.private_key_path, role="operator"), expected_coordinator_id=selected if selected is not None else config.expected_coordinator_id)

    def observe_status(self) -> OperatorObservation:
        """Read accepted configuration; unreachable services retain known identity."""
        from loom.queue.operations import OperatorObservation
        from loom.timestamps import utc_timestamp
        try:
            result = cast(OperatorObservation, self._native_call("operator_status", {}))
            self._retained_status = result
            return result
        except CoordinatorClientError as exc:
            if exc.code not in {"unavailable", "deadline_exceeded"}:
                raise
            owner = self._expected_coordinator_id
            if owner is None and self._last_connection is not None:
                owner = self._last_connection.coordinator_id
            retained = self._retained_status
            return OperatorObservation(owner, utc_timestamp(), None if retained is None else retained.revision,
                "unknown" if retained is None else "retained", "unavailable",
                {} if retained is None else {**retained.value, "retained_observed_at": retained.observed_at}, exc.code)

    def observe_agent(self, agent_id: str) -> OperatorObservation:
        """Observe one agent without interpreting stale capacity as available."""
        return self._native_call("operator_agent", {"agent_id": agent_id})

    def observe_assignment(self, assignment_id: str) -> OperatorObservation:
        """Observe one assignment; local claims remain independently sourced."""
        return self._native_call("operator_assignment", {"assignment_id": assignment_id})

    def control_agent(self, control: AgentControl, *, expected_coordinator_id: str | None = None, condition: Mapping[str, PlainData] | None = None) -> Mapping[str, PlainData]:
        """Commit/replay a native control with optional predecessor ownership.

        ``condition={"expected_control_id": id}`` requires that exact latest
        control; an explicit null ID requires no prior control. Omission retains
        unconditional operator behavior. The condition is immutable intent and
        is compared atomically only for fresh acceptance, never during replay.
        """
        from loom.queue.operations import control_intent_digest
        value = control.value()
        payload: dict[str, PlainData] = {"control": value}
        if condition is not None:
            payload["condition"] = dict(condition)
        payload["intent_digest"] = control_intent_digest(value if condition is None else {"control": value, "condition": dict(condition)})
        return self._native_call("operator_control", payload, expected_coordinator_id)

    def observe_control(self, operation_id: str) -> Mapping[str, PlainData]:
        """Resolve the original operation after a lost mutation response."""
        return self._native_call("operator_operation", {"operation_id": operation_id})

    def observe_maintenance(self) -> Mapping[str, PlainData]:
        """Read current native gate ownership, revision and check permissions."""
        return self._native_call("operator_maintenance", {})

    def maintenance(self, control: Mapping[str, PlainData], *, expected_coordinator_id: str | None = None) -> Mapping[str, PlainData]:
        """Apply an exact gate control; retain its intent for lost-reply recovery.

        Controls carry operation/maintenance IDs, maintenance intent digest,
        action (close/open/authorize/revoke), expected revision and check binding.
        See the queue maintenance contract for check fields and resource units.
        """
        from loom.queue.operations import control_intent_digest
        return self._native_call("operator_maintenance_control", {"control": dict(control), "intent_digest": control_intent_digest(control)}, expected_coordinator_id)

    def maintenance_operation(self, operation_id: str) -> Mapping[str, PlainData]:
        """Observe the original mutation; an unknown ID never submits work."""
        return self._native_call("operator_maintenance_operation", {"operation_id": operation_id})
