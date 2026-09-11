"""Coordinator-owned preparation intent, claims and reconciliation.

Executable composition remains behind the application callbacks. This owner uses
the ordinary admission and assignment owners for all child execution and release
proof, and never holds the daemon's cycle lock during capture or publication.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
from threading import Lock
from typing import TYPE_CHECKING, Protocol, cast

from loom.artifacts import ArtifactRef
from loom.pipeline.runtime.options import RunOptions
from loom.pipeline.cleanup.preparation_pins import retain_preparation_path
from loom.serialization import PlainData, stable_json_bytes

from .errors import QueueConflictError, QueueServiceError
from .preparation import (
    PreparationChildInput,
    PrepareRunRequest,
    SharedInputReceipt,
    capture_shared_input,
    discard_shared_input_temporaries,
)

if TYPE_CHECKING:
    from .managed_local_preparation import ManagedLocalPreparationReceipt
    from .local_daemon import (
        LocalDaemon,
        LocalDaemonAdmission,
        LocalDaemonConfig,
        LocalDaemonOperation,
    )


PREPARATION_RUN_PREFIX = "loom-preparation-"
_MAX_RESULT_BYTES = 64 * 1024
_TERMINAL = frozenset({"applied", "failed", "cancelled", "conflict"})
_LOGGER = logging.getLogger(__name__)


class PreparationNotAccepted(QueueServiceError):
    """An acceptance refusal proven to precede the durable transaction commit."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PreparationChildReserved(QueueConflictError):
    """Public child submission refused before native admission can mutate state."""

    code = "conflict"


@dataclass(frozen=True, slots=True)
class PreparationReport:
    """One checked committed report, retained only for the current publication pass."""

    reference: ArtifactRef
    preflight: Mapping[str, PlainData]
    preflight_status: str
    publishable: bool
    prospective_receipt: ManagedLocalPreparationReceipt | None
    publication_data: object


class PreparationCallbacks(Protocol):
    """Application wiring above queue; no project composition enters this owner."""

    def validate_config(self, config: LocalDaemonConfig) -> None: ...

    def prepare_child(
        self,
        config: LocalDaemonConfig,
        binding: PreparationChildInput,
        run_name: str,
        options: RunOptions,
    ) -> ManagedLocalPreparationReceipt: ...

    def read_report(
        self,
        config: LocalDaemonConfig,
        admission: LocalDaemonAdmission,
        request: PrepareRunRequest,
        binding: PreparationChildInput,
    ) -> PreparationReport: ...

    def publish_target(
        self,
        config: LocalDaemonConfig,
        request: PrepareRunRequest,
        report: PreparationReport,
    ) -> ManagedLocalPreparationReceipt: ...


class PreparationConfigurationUnavailable(QueueServiceError):
    """The accepted scheduling implementation is not currently available."""


class PreparationInstallationMismatch(QueueConflictError):
    """A report names software different from the accepted worker installation."""


class _ResultTooLarge(QueueServiceError):
    pass


def scheduling_snapshot(config: LocalDaemonConfig) -> dict[str, PlainData]:
    components = config.scheduling_components
    return {
        "planners": [item.descriptor.to_dict() for item in components.planners],
        "hard_evaluators": [
            item.descriptor.to_dict() for item in components.hard_evaluators
        ],
        "preference_scorers": [
            item.descriptor.to_dict() for item in components.preference_scorers
        ],
        "policy": components.policy.descriptor.to_dict(),
    }


def _operation(
    operation_id: str, state: str, code: str | None, result: Mapping[str, PlainData]
) -> LocalDaemonOperation:
    from .local_daemon import LocalDaemonOperation

    value = LocalDaemonOperation.from_dict(
        {
            "operation_id": operation_id,
            "kind": "prepare_run",
            "state": state,
            "code": code,
            "result": dict(result),
        }
    )
    if len(stable_json_bytes(value.to_dict())) > _MAX_RESULT_BYTES:
        raise _ResultTooLarge("preparation result_too_large")
    return value


def _with_report(
    operation_id: str,
    state: str,
    code: str | None,
    result: Mapping[str, PlainData],
    preflight: Mapping[str, PlainData] | None,
) -> LocalDaemonOperation:
    required = {**result, "preflight": None}
    if state in {"pending", "applying"}:
        _operation(operation_id, "cancelled", "invalid_preparation_report", required)
    value = _operation(operation_id, state, code, required)
    if preflight is not None:
        try:
            return _operation(
                operation_id, state, code, {**required, "preflight": dict(preflight)}
            )
        except _ResultTooLarge:
            pass
    return value


def _json(value: object) -> str:
    return stable_json_bytes(value).decode("utf-8")


def _mapping(value: object) -> dict[str, PlainData]:
    if not isinstance(value, dict):
        raise QueueServiceError("retained preparation value is invalid")
    return cast(dict[str, PlainData], value)


class CoordinatorPreparations:
    """Advance retained operations while the daemon owns its exclusive root lock."""

    def __init__(
        self, daemon: LocalDaemon, callbacks: PreparationCallbacks | None
    ) -> None:
        self.daemon = daemon
        self.callbacks = callbacks
        self._reconcile_lock = Lock()
        self._cursor = 0

    @property
    def available(self) -> bool:
        if self.callbacks is None or not self.daemon.config.preparation_enabled:
            return False
        try:
            self.callbacks.validate_config(self.daemon.config)
        except QueueServiceError:
            return False
        return True

    def contains(self, operation_id: str) -> bool:
        with self.daemon._connection() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM preparation_operations WHERE operation_id = ?",
                    (operation_id,),
                ).fetchone()
                is not None
            )

    def accept(
        self, request: PrepareRunRequest, principal_id: str
    ) -> LocalDaemonOperation:
        try:
            return self._accept(request, principal_id)
        except QueueServiceError as exc:
            code = "invalid_request"
            if (
                "unsupported" in str(exc)
                or "does not support" in str(exc)
                or "requires embedded authority" in str(exc)
            ):
                code = "unsupported"
            raise PreparationNotAccepted(code, str(exc)) from exc

    def _accept(
        self, request: PrepareRunRequest, principal_id: str
    ) -> LocalDaemonOperation:
        from .local_daemon import _operation_projection

        if not isinstance(request, PrepareRunRequest):
            raise QueueServiceError("prepare request is invalid")
        intent = request.intent_digest(principal_id)
        coordinator_id = self.daemon._require_started()
        with self.daemon._cycle_lock, self.daemon._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM preparation_operations WHERE operation_id = ?",
                (request.operation_id,),
            ).fetchone()
            if row is not None:
                if (
                    row["principal_id"] != principal_id
                    or row["intent_digest"] != intent
                ):
                    raise QueueConflictError("preparation operation intent conflicts")
                return self._projection(row)
            if not self.available or self.callbacks is None:
                raise QueueServiceError("preparation is unsupported")
            if request.source.mode != "shared":
                raise QueueServiceError("staged preparation input is unsupported")
            if request.run_name.startswith(PREPARATION_RUN_PREFIX):
                raise QueueServiceError("preparation target uses a reserved child name")
            policy = self.daemon.config.preparation_policy
            assert policy is not None
            selected = policy.select(request)
            selected["run_store_root"] = str(self.daemon.config.run_store_root)
            selected["scheduling"] = scheduling_snapshot(self.daemon.config)
            if _operation_projection(conn, request.operation_id) is not None:
                raise QueueConflictError("managed operation identity is ambiguous")
            execution = self.daemon._execution
            if (
                execution is not None
                and execution.operation_projection(request.operation_id) is not None
            ):
                raise QueueConflictError("managed operation identity is ambiguous")
            if (
                conn.execute(
                    "SELECT 1 FROM preparation_operations WHERE target_name = ?",
                    (request.run_name,),
                ).fetchone()
                is not None
            ):
                raise QueueConflictError(
                    "preparation target is reserved by another operation"
                )
            child_name = (
                PREPARATION_RUN_PREFIX
                + hashlib.sha256(request.operation_id.encode()).hexdigest()
            )
            result: dict[str, PlainData] = {
                "schema_version": 1,
                "coordinator_id": coordinator_id,
                "input_receipt": None,
                "preparation_admission_id": None,
                "preflight_status": None,
                "preflight": None,
                "report_ref": None,
                "prepared_run": None,
                "evidence_refs": [],
            }
            # Reserve enough outer-envelope space to report a terminal failure
            # even for an identifier near the native projection limit.
            _operation(
                request.operation_id, "cancelled", "invalid_preparation_report", result
            )
            operation = _operation(request.operation_id, "pending", None, result)
            conn.execute(
                "INSERT INTO preparation_operations(operation_id, principal_id, intent_digest, request_json, selected_json, target_name, child_name, state, result_json) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                (
                    request.operation_id,
                    principal_id,
                    intent,
                    _json(request.to_dict()),
                    _json(selected),
                    request.run_name,
                    child_name,
                    _json(result),
                ),
            )
            conn.commit()
        self.daemon._wake.set()
        return operation

    def cancel(self, operation_id: str, principal_id: str) -> LocalDaemonOperation:
        with self.daemon._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM preparation_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise QueueServiceError("managed preparation operation was not found")
            if row["principal_id"] != principal_id:
                raise QueueConflictError(
                    "preparation operation belongs to another principal"
                )
            if row["state"] not in _TERMINAL:
                conn.execute(
                    "UPDATE preparation_operations SET cancellation_requested = 1 WHERE operation_id = ?",
                    (operation_id,),
                )
                conn.commit()
            operation = self._projection(row)
        self.daemon._wake.set()
        return operation

    def reconcile(self) -> None:
        if self.callbacks is None or not self._reconcile_lock.acquire(blocking=False):
            return
        try:
            with self.daemon._connection() as conn:
                rows = tuple(
                    conn.execute(
                        "SELECT rowid AS sequence, * FROM preparation_operations WHERE rowid > ? AND state IN ('pending', 'applying') ORDER BY rowid LIMIT 32",
                        (self._cursor,),
                    )
                )
            if not rows:
                self._cursor = 0
                return
            for row in rows:
                self._cursor = int(row["sequence"])
                try:
                    self._advance(row)
                except PreparationConfigurationUnavailable:
                    # Existing retained-component rules require a matching
                    # protected implementation; never redirect to a new one.
                    continue
                except Exception:
                    # A lost result after a durable action is reconciled from
                    # its original claim. It must not starve ordinary jobs or
                    # turn an unknown publication into a fabricated failure.
                    current = self._read(str(row["operation_id"]))
                    if (
                        current["state"] not in _TERMINAL
                        and current["result_code"] != "preparation_unavailable"
                    ):
                        result = _mapping(json.loads(str(current["result_json"])))
                        preflight = (
                            None
                            if result["preflight"] is None
                            else _mapping(result["preflight"])
                        )
                        self._store_result(
                            _with_report(
                                str(current["operation_id"]),
                                str(current["state"]),
                                "preparation_unavailable",
                                result,
                                preflight,
                            )
                        )
                        _LOGGER.exception(
                            "Preparation reconciliation is unavailable for %.80s",
                            row["operation_id"],
                        )
        finally:
            self._reconcile_lock.release()

    def _read(self, operation_id: str) -> sqlite3.Row:
        with self.daemon._connection() as conn:
            row = conn.execute(
                "SELECT * FROM preparation_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
        if row is None:
            raise QueueConflictError("retained preparation operation disappeared")
        return row

    @staticmethod
    def _projection(row: sqlite3.Row) -> LocalDaemonOperation:
        return _operation(
            str(row["operation_id"]),
            str(row["state"]),
            None if row["result_code"] is None else str(row["result_code"]),
            _mapping(json.loads(str(row["result_json"]))),
        )

    def _store_result(self, operation: LocalDaemonOperation) -> None:
        with self.daemon._connection() as conn:
            conn.execute(
                "UPDATE preparation_operations SET state = ?, result_code = ?, result_json = ? WHERE operation_id = ?",
                (
                    operation.state,
                    operation.code,
                    _json(operation.result),
                    operation.operation_id,
                ),
            )
            conn.commit()
        self.daemon._wake.set()

    def _fail(self, row: sqlite3.Row, code: str, *, conflict: bool = False) -> None:
        result = _mapping(json.loads(str(row["result_json"])))
        preflight = (
            None if result["preflight"] is None else _mapping(result["preflight"])
        )
        self._store_result(
            _with_report(
                str(row["operation_id"]),
                "conflict" if conflict else "failed",
                code,
                result,
                preflight,
            )
        )

    def _configuration(self, selected: Mapping[str, PlainData]) -> LocalDaemonConfig:
        from loom.pipeline.stores.coordinator_authority import (
            embedded_coordinator_authority,
        )

        execution = self.daemon._execution
        if execution is None:
            raise PreparationConfigurationUnavailable(
                "preparation execution owner is unavailable"
            )
        with self.daemon._cycle_lock:
            components = execution.preparation_scheduling_components(
                _mapping(selected["scheduling"])
            )
            return replace(
                self.daemon.config,
                run_store_root=Path(cast(str, selected["run_store_root"])),
                scheduling_components=components,
                slurm_profiles=(),
                coordinator_authority_factory=embedded_coordinator_authority,
            )

    def _advance(self, row: sqlite3.Row) -> None:
        from .local_daemon import LocalDaemonAdmissionRequest, LocalDaemonAdmissionState

        callbacks = self.callbacks
        assert callbacks is not None
        operation_id = str(row["operation_id"])
        # Another caller may have cancelled after this reconciliation page was
        # selected. Only this reconciler mutates execution/publication progress.
        row = self._read(operation_id)
        if row["state"] in _TERMINAL:
            return
        result = _mapping(json.loads(str(row["result_json"])))
        request = PrepareRunRequest.from_dict(
            _mapping(json.loads(str(row["request_json"])))
        )
        selected = _mapping(json.loads(str(row["selected_json"])))
        if (
            row["cancellation_requested"]
            and row["state"] == "pending"
            and not row["dispatch_claimed"]
        ):
            if result["input_receipt"] is None and request.source.mode == "shared":
                root = _mapping(selected["source_root"])
                discard_shared_input_temporaries(
                    request,
                    snapshot_root=Path(cast(str, root["shared_snapshot_root"])),
                    owner_id=self.daemon._require_started(),
                )
            self._store_result(_operation(operation_id, "cancelled", None, result))
            return
        config = self._configuration(selected)
        profile = _mapping(selected["profile"])
        receipt_data = result["input_receipt"]
        if receipt_data is None:
            root = _mapping(selected["source_root"])
            try:
                snapshot_root = Path(cast(str, root["shared_snapshot_root"]))
                owner_id = self.daemon._require_started()
                discard_shared_input_temporaries(
                    request, snapshot_root=snapshot_root, owner_id=owner_id
                )
                receipt = capture_shared_input(
                    request,
                    source_root=Path(cast(str, root["path"])),
                    snapshot_root=snapshot_root,
                    owner_id=owner_id,
                )
                retain_preparation_path(
                    snapshot_root / receipt.path,
                    coordinator_id=owner_id,
                    operation_id=operation_id,
                )
                result["input_receipt"] = receipt.to_dict()
                _with_report(operation_id, "pending", None, result, None)
                self._store_result(_operation(operation_id, "pending", None, result))
            except (QueueServiceError, OSError) as exc:
                code = next(
                    (
                        code
                        for code in (
                            "source_changed",
                            "input_limit_exceeded",
                            "result_too_large",
                        )
                        if code in str(exc)
                    ),
                    "source_unavailable",
                )
                self._fail(row, code)
                return
            row = self._read(operation_id)
        else:
            receipt = SharedInputReceipt.from_dict(_mapping(receipt_data))
        binding = PreparationChildInput(
            request.operation_id,
            request.preparation_profile,
            request.config_path,
            receipt,
            _mapping(profile["profile_descriptor"]),
        )
        child_name = str(row["child_name"])
        if row["child_admission_id"] is None:
            try:
                _with_report(
                    operation_id,
                    "pending",
                    None,
                    {**result, "preparation_admission_id": "admission-" + "f" * 36},
                    None,
                )
            except _ResultTooLarge:
                self._fail(row, "result_too_large")
                return
            if row["cancellation_requested"] and not row["dispatch_claimed"]:
                self._store_result(_operation(operation_id, "cancelled", None, result))
                return
            if not row["dispatch_claimed"]:
                try:
                    retain_preparation_path(
                        config.run_store_root / child_name,
                        coordinator_id=self.daemon._require_started(),
                        operation_id=operation_id,
                    )
                    child_receipt = callbacks.prepare_child(
                        config,
                        binding,
                        child_name,
                        RunOptions.from_dict(profile["runtime_options"]),
                    )
                except (QueueServiceError, QueueConflictError):
                    self._fail(row, "preparation_child_failed")
                    return
                child_uri = child_receipt.run_uri
                with self.daemon._connection() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    current = conn.execute(
                        "SELECT cancellation_requested FROM preparation_operations WHERE operation_id = ?",
                        (operation_id,),
                    ).fetchone()
                    assert current is not None
                    if current["cancellation_requested"]:
                        conn.commit()
                        return
                    conn.execute(
                        "UPDATE preparation_operations SET dispatch_claimed = 1 WHERE operation_id = ?",
                        (operation_id,),
                    )
                    conn.commit()
            else:
                from loom.pipeline.stores import path_to_run_uri

                # The durable dispatch claim proves child publication completed.
                # Its admission may already have run after a lost submit reply;
                # rejoin that admission without replanning an executed child.
                child_uri = path_to_run_uri(config.run_store_root / child_name)
            admission = self.daemon._submit(
                LocalDaemonAdmissionRequest(child_name, child_uri),
                preparation_operation_id=operation_id,
            )
            result["preparation_admission_id"] = admission.admission_id
            projected = _operation(operation_id, "pending", None, result)
            with self.daemon._connection() as conn:
                conn.execute(
                    "UPDATE preparation_operations SET child_admission_id = ?, result_json = ? WHERE operation_id = ?",
                    (admission.admission_id, _json(projected.result), operation_id),
                )
                conn.commit()
            row = self._read(operation_id)
        admission = self.daemon._admission(str(row["child_admission_id"]))
        terminal = {
            LocalDaemonAdmissionState.SUCCEEDED,
            LocalDaemonAdmissionState.FAILED,
            LocalDaemonAdmissionState.CANCELLED,
        }
        if row["cancellation_requested"] and row["state"] == "pending":
            admission = self.daemon._cancel(
                child_name, principal_id=str(row["principal_id"])
            )
            execution = self.daemon._execution
            assert execution is not None
            with self.daemon._cycle_lock:
                released = (
                    execution.coordinator.run_active_assignment_count(admission.run_uri)
                    == 0
                )
            if admission.state in terminal and released:
                self._store_result(_operation(operation_id, "cancelled", None, result))
            return
        if admission.state in {
            LocalDaemonAdmissionState.FAILED,
            LocalDaemonAdmissionState.CANCELLED,
        }:
            self._fail(row, "preparation_child_failed")
            return
        if admission.state is not LocalDaemonAdmissionState.SUCCEEDED:
            return
        try:
            report = callbacks.read_report(config, admission, request, binding)
            result.update(
                report_ref=report.reference.to_dict(),
                preflight_status=report.preflight_status,
            )
            projected = _with_report(
                operation_id, str(row["state"]), None, result, report.preflight
            )
        except _ResultTooLarge:
            self._fail(row, "result_too_large")
            return
        except (QueueServiceError, QueueConflictError) as exc:
            if row["state"] == "applying":
                # Publication may already have completed. Keep its durable
                # claim until the pinned report can prove the actual outcome.
                raise
            self._fail(
                row,
                "installation_mismatch"
                if isinstance(exc, PreparationInstallationMismatch)
                else "invalid_preparation_report",
            )
            return
        if not report.publishable:
            self._store_result(
                _with_report(
                    operation_id, "failed", "preflight_failed", result, report.preflight
                )
            )
            return
        assert report.prospective_receipt is not None
        try:
            _with_report(
                operation_id,
                "applied",
                None,
                {**result, "prepared_run": report.prospective_receipt.to_dict()},
                report.preflight,
            )
        except _ResultTooLarge:
            self._store_result(
                _with_report(
                    operation_id, "failed", "result_too_large", result, report.preflight
                )
            )
            return
        if row["state"] == "pending":
            retain_preparation_path(
                config.run_store_root / request.run_name,
                coordinator_id=self.daemon._require_started(),
                operation_id=operation_id,
            )
            with self.daemon._connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                claimed = conn.execute(
                    "UPDATE preparation_operations SET state = 'applying', result_json = ? WHERE operation_id = ? AND state = 'pending' AND cancellation_requested = 0",
                    (_json(projected.result), operation_id),
                ).rowcount
                conn.commit()
            if not claimed:
                return
        try:
            prepared = callbacks.publish_target(config, request, report)
        except QueueConflictError:
            self._fail(self._read(operation_id), "publication_conflict", conflict=True)
            return
        # Unknown publication failures leave the durable claim applying. The
        # next pass uses native complete replay or native partial-target conflict.
        result["prepared_run"] = prepared.to_dict()
        self._store_result(
            _with_report(operation_id, "applied", None, result, report.preflight)
        )
