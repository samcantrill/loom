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
from loom.io.uris import uri_to_path
from loom.pipeline.runtime.options import RunOptions
from loom.pipeline.cleanup.preparation_pins import retain_preparation_path
from loom.serialization import PlainData, stable_json_bytes

from .errors import QueueConflictError, QueueServiceError
from .run import RunRequest, _public_operation_id
from .preparation import (
    PreparationChildInput,
    PrepareRunRequest,
    capture_shared_input,
    capture_staged_input,
    discard_shared_input_temporaries,
    discard_staged_input_temporaries,
    input_receipt_from_dict,
)

if TYPE_CHECKING:
    from .managed_local_preparation import ManagedLocalPreparationReceipt
    from .local_daemon import (
        LocalDaemon,
        LocalDaemonAdmission,
        LocalDaemonAdmissionRequest,
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


def _cancel_id(operation_id: str) -> str:
    return "cancel-run-" + hashlib.sha256(operation_id.encode()).hexdigest()


def _operation(
    operation_id: str, state: str, code: str | None, result: Mapping[str, PlainData]
) -> LocalDaemonOperation:
    from .local_daemon import LocalDaemonOperation

    value = LocalDaemonOperation.from_dict(
        {
            "operation_id": operation_id,
            "kind": "cancel_run"
            if "target_operation_id" in result
            else "run"
            if "queue_item_id" in result
            else "prepare_run",
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
    reserved = required
    if "queue_item_id" in required:
        reserved = {**required, "cancellation_operation_id": _cancel_id(operation_id)}
    if state in {"pending", "applying"} or "queue_item_id" in required:
        _operation(operation_id, "cancelled", "invalid_preparation_report", reserved)
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
    if not isinstance(value, Mapping):
        raise QueueServiceError("retained preparation value is invalid")
    return cast(dict[str, PlainData], dict(value))


class CoordinatorPreparations:
    """Advance retained operations while the daemon owns its exclusive root lock."""

    def __init__(
        self, daemon: LocalDaemon, callbacks: PreparationCallbacks | None
    ) -> None:
        self.daemon = daemon
        self.callbacks = callbacks
        self._reconcile_lock = Lock()
        self._cursor = 0
        self._cancel_cursor = 0

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

    def accept_run(
        self, request: RunRequest, principal_id: str
    ) -> LocalDaemonOperation:
        if not isinstance(request, RunRequest):
            raise PreparationNotAccepted("invalid_request", "run request is invalid")
        try:
            return self._accept(
                request.preparation, principal_id, queue_item_id=request.queue_item_id
            )
        except QueueServiceError as exc:
            raise PreparationNotAccepted(
                "unsupported" if "unsupported" in str(exc) else "invalid_request",
                str(exc),
            ) from exc

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
        self,
        request: PrepareRunRequest,
        principal_id: str,
        *,
        queue_item_id: str | None = None,
    ) -> LocalDaemonOperation:
        from .local_daemon import _operation_projection

        if not isinstance(request, PrepareRunRequest):
            raise QueueServiceError("prepare request is invalid")
        _public_operation_id(request.operation_id)
        kind = "prepare_run" if queue_item_id is None else "run"
        intent = request.intent_digest(principal_id)
        if queue_item_id is not None:
            if queue_item_id.startswith(PREPARATION_RUN_PREFIX):
                raise QueueServiceError("run queue identity is reserved")
            intent = hashlib.sha256(
                stable_json_bytes([intent, kind, queue_item_id])
            ).hexdigest()
        coordinator_id = self.daemon._require_started()
        with self.daemon._cycle_lock, self.daemon._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM preparation_operations WHERE operation_id = ?",
                (request.operation_id,),
            ).fetchone()
            if row is not None:
                if (
                    row["kind"] != kind
                    or row["principal_id"] != principal_id
                    or row["intent_digest"] != intent
                ):
                    raise QueueConflictError("preparation operation intent conflicts")
                return self._projection(row)
            if not self.available or self.callbacks is None:
                raise QueueServiceError("preparation is unsupported")
            if request.run_name.startswith(PREPARATION_RUN_PREFIX):
                raise QueueServiceError("preparation target uses a reserved child name")
            policy = self.daemon.config.preparation_policy
            assert policy is not None
            selected = policy.select(request)
            selected["run_store_root"] = str(self.daemon.config.run_store_root)
            selected["scheduling"] = scheduling_snapshot(self.daemon.config)
            from loom.pipeline.stores.coordinator_authority import (
                coordinator_authority_identity,
            )

            selected["authority"] = coordinator_authority_identity(
                self.daemon.config.coordinator_authority_factory
            )
            selected["slurm_profiles"] = [
                item.descriptor.to_dict() for item in self.daemon.config.slurm_profiles
            ]
            selected["remote_profiles"] = [
                item.to_dict() for item in self.daemon.config.remote_profiles
            ]
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
            if queue_item_id is not None:
                if (
                    conn.execute(
                        "SELECT 1 FROM preparation_operations WHERE queue_item_id = ?",
                        (queue_item_id,),
                    ).fetchone()
                    is not None
                    or conn.execute(
                        "SELECT 1 FROM managed_admissions WHERE queue_item_id = ?",
                        (queue_item_id,),
                    ).fetchone()
                    is not None
                ):
                    raise QueueConflictError("run queue identity is already reserved")
                result.update(
                    queue_item_id=queue_item_id,
                    admission=None,
                    cancellation_operation_id=None,
                )
                self._check_run_budget(request.operation_id, result)
            # Reserve enough outer-envelope space to report a terminal failure
            # even for an identifier near the native projection limit.
            _operation(
                request.operation_id, "cancelled", "invalid_preparation_report", result
            )
            operation = _operation(request.operation_id, "pending", None, result)
            conn.execute(
                "INSERT INTO preparation_operations(operation_id, principal_id, kind, queue_item_id, intent_digest, request_json, selected_json, target_name, child_name, state, result_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                (
                    request.operation_id,
                    principal_id,
                    kind,
                    queue_item_id,
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
            if row["kind"] != "prepare_run":
                raise QueueConflictError("use cancel_run_operation for run intent")
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
            self._reconcile_cancellations()
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
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                "SELECT result_json FROM preparation_operations WHERE operation_id = ?",
                (operation.operation_id,),
            ).fetchone()
            if operation.kind == "run" and current is not None:
                result = _mapping(operation.result)
                result["cancellation_operation_id"] = json.loads(
                    str(current["result_json"])
                )["cancellation_operation_id"]
                operation = _with_report(
                    operation.operation_id,
                    operation.state,
                    operation.code,
                    result,
                    None
                    if result["preflight"] is None
                    else _mapping(result["preflight"]),
                )
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
            coordinator_authority_identity,
        )

        execution = self.daemon._execution
        if execution is None:
            raise PreparationConfigurationUnavailable(
                "preparation execution owner is unavailable"
            )
        with self.daemon._cycle_lock:
            if (
                coordinator_authority_identity(
                    self.daemon.config.coordinator_authority_factory
                )
                != selected["authority"]
            ):
                raise PreparationConfigurationUnavailable(
                    "accepted preparation authority is unavailable"
                )
            available = tuple(execution.slurm_profiles.values())
            profiles = []
            for descriptor in cast(list[PlainData], selected["slurm_profiles"]):
                profile = next(
                    (
                        item
                        for item in available
                        if item.descriptor.to_dict() == descriptor
                    ),
                    None,
                )
                if profile is None:
                    raise PreparationConfigurationUnavailable(
                        "accepted preparation Slurm profile is unavailable"
                    )
                profiles.append(profile)
            remote_profiles = []
            for descriptor in cast(list[PlainData], selected["remote_profiles"]):
                remote = next(
                    (
                        item
                        for item in self.daemon.config.remote_profiles
                        if item.to_dict() == descriptor
                    ),
                    None,
                )
                if remote is None:
                    raise PreparationConfigurationUnavailable(
                        "accepted preparation remote profile is unavailable"
                    )
                remote_profiles.append(remote)
            components = execution.preparation_scheduling_components(
                _mapping(selected["scheduling"])
            )
            return replace(
                self.daemon.config,
                run_store_root=Path(cast(str, selected["run_store_root"])),
                scheduling_components=components,
                slurm_profiles=tuple(profiles),
                remote_profiles=tuple(remote_profiles),
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
        if row["kind"] == "run" and result["prepared_run"] is not None:
            self._continue_run(row)
            return
        request = PrepareRunRequest.from_dict(
            _mapping(json.loads(str(row["request_json"])))
        )
        selected = _mapping(json.loads(str(row["selected_json"])))
        if (
            row["cancellation_requested"]
            and row["state"] == "pending"
            and not row["dispatch_claimed"]
        ):
            if result["input_receipt"] is None and request.source.mode == "staged":
                discard_staged_input_temporaries(
                    request,
                    artifact_root=self.daemon.config.coordinator_root
                    / "preparation-inputs",
                    owner_id=self.daemon._require_started(),
                )
            elif result["input_receipt"] is None:
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
                owner_id = self.daemon._require_started()
                if request.source.mode == "staged":
                    artifact_root = config.coordinator_root / "preparation-inputs"
                    discard_staged_input_temporaries(
                        request, artifact_root=artifact_root, owner_id=owner_id
                    )
                    receipt = capture_staged_input(
                        request,
                        source_root=Path(cast(str, root["path"])),
                        artifact_root=artifact_root,
                        owner_id=owner_id,
                    )
                    captured_path = uri_to_path(receipt.reference.uri)
                else:
                    snapshot_root = Path(cast(str, root["shared_snapshot_root"]))
                    discard_shared_input_temporaries(
                        request, snapshot_root=snapshot_root, owner_id=owner_id
                    )
                    receipt = capture_shared_input(
                        request,
                        source_root=Path(cast(str, root["path"])),
                        snapshot_root=snapshot_root,
                        owner_id=owner_id,
                    )
                    captured_path = snapshot_root / receipt.path
                retain_preparation_path(
                    captured_path,
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
            receipt = input_receipt_from_dict(_mapping(receipt_data))
        binding = PreparationChildInput(
            request.operation_id,
            request.preparation_profile,
            request.config_path,
            receipt,
            _mapping(profile["profile_descriptor"]),
            request.overlays,
            request.overrides,
            request.run_options,
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
                conn.execute("BEGIN IMMEDIATE")
                if row["kind"] == "run":
                    current = conn.execute(
                        "SELECT result_json FROM preparation_operations WHERE operation_id = ?",
                        (operation_id,),
                    ).fetchone()
                    assert current is not None
                    result["cancellation_operation_id"] = json.loads(
                        str(current["result_json"])
                    )["cancellation_operation_id"]
                    projected = _operation(operation_id, "pending", None, result)
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
            if row["kind"] == "run":
                self._check_run_budget(
                    operation_id,
                    {**result, "prepared_run": report.prospective_receipt.to_dict()},
                )
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
            _with_report(
                operation_id,
                "applying" if row["kind"] == "run" else "applied",
                None,
                result,
                report.preflight,
            )
        )
        if row["kind"] == "run":
            self._continue_run(self._read(operation_id))

    def _check_run_budget(
        self, operation_id: str, result: Mapping[str, PlainData]
    ) -> None:
        """Reserve mandatory native references before publication, never trim them.

        Native admission identifiers/digests/timestamps are fixed-width. The
        reserve covers SQLite integer widths and the full acceptance receipt;
        later mutable admission detail is deliberately queried separately.
        """
        prepared = result.get("prepared_run")
        run_uri = _mapping(prepared)["run_uri"] if prepared is not None else ""
        admission: dict[str, PlainData] = {
            "admission_id": "admission-" + "f" * 36,
            "queue_item_id": result["queue_item_id"],
            "coordinator_id": result["coordinator_id"],
            "run_uri": run_uri,
            "intent_digest": "f" * 64,
            "execution_owner": "managed-stage",
            "state": "PENDING_AUTHORITY",
            "accepted_at": "9" * 40,
            "authority_operation_id": "authority-bind-" + "f" * 36,
            "revision": 9223372036854775807,
            "run_priority": -9223372036854775808,
            "enqueue_sequence": 9223372036854775807,
            "cancellation_operation_id": None,
            "cancellation_principal_id": None,
            "blocked_reason": None,
        }
        cancel_id = _cancel_id(operation_id)
        _with_report(
            operation_id,
            "applied",
            "invalid_preparation_report",
            {**result, "admission": admission, "cancellation_operation_id": cancel_id},
            None,
        )
        _operation(
            cancel_id,
            "applied",
            "invalid_preparation_report",
            {
                "coordinator_id": result["coordinator_id"],
                "target_operation_id": operation_id,
                "queue_item_id": result["queue_item_id"],
                "admission": admission,
                "native_cancellation_operation_id": "authority-cancel-" + "f" * 36,
                "native_control": {
                    "admission_id": "admission-" + "f" * 36,
                    "state": "CANCELLATION_REQUESTED",
                    "revision": 9223372036854775807,
                },
            },
        )

    def check_target_submission(
        self, request: LocalDaemonAdmissionRequest, operation_id: str | None
    ) -> None:
        from loom.pipeline.stores import path_to_run_uri, run_uri_to_path

        try:
            run_name = run_uri_to_path(request.run_uri).name
        except ValueError:
            run_name = ""
        with self.daemon._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM preparation_operations WHERE kind = 'run' "
                "AND (queue_item_id = ? OR target_name = ?)",
                (request.queue_item_id, run_name),
            ).fetchall()
        for row in rows:
            selected = _mapping(json.loads(str(row["selected_json"])))
            uri = path_to_run_uri(
                Path(cast(str, selected["run_store_root"])) / str(row["target_name"])
            )
            if row["queue_item_id"] != request.queue_item_id and uri != request.run_uri:
                continue
            if row["queue_item_id"] != request.queue_item_id or uri != request.run_uri:
                raise QueueConflictError("reserved run admission identity conflicts")
            if operation_id == row["operation_id"]:
                if row["cancellation_requested"] or row["state"] in _TERMINAL:
                    raise QueueConflictError(
                        "run continuation is suppressed or complete"
                    )
            elif row["state"] != "applied":
                raise QueueConflictError("target admission belongs to a run operation")

    def retain_admission(
        self,
        conn: sqlite3.Connection,
        operation_id: str,
        admission: LocalDaemonAdmission,
    ) -> None:
        """Commit the immutable acceptance projection with the native admission."""
        row = conn.execute(
            "SELECT * FROM preparation_operations WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        assert row is not None
        result = _mapping(json.loads(str(row["result_json"])))
        result["admission"] = admission.to_dict()
        projected = _with_report(
            operation_id,
            "applied",
            None,
            result,
            None if result["preflight"] is None else _mapping(result["preflight"]),
        )
        conn.execute(
            "UPDATE preparation_operations SET state = 'applied', result_code = NULL, result_json = ? WHERE operation_id = ?",
            (_json(projected.result), operation_id),
        )

    def _continue_run(self, row: sqlite3.Row) -> None:
        from .local_daemon import AdmissionNotFoundError, LocalDaemonAdmissionRequest

        operation_id = str(row["operation_id"])
        # Same lock as native admission: cancellation cannot acknowledge
        # suppression while admission is in flight, including a lost reply.
        with self.daemon._cycle_lock:
            row = self._read(operation_id)
            if row["state"] in _TERMINAL:
                return
            result = _mapping(json.loads(str(row["result_json"])))
            prepared = _mapping(result["prepared_run"])
            try:
                admission = self.daemon.admission_for_queue_item(
                    str(row["queue_item_id"])
                )
            except AdmissionNotFoundError:
                admission = None
            if admission is not None:
                if admission.run_uri != prepared["run_uri"]:
                    self._fail(row, "admission_conflict", conflict=True)
                    return
                with self.daemon._connection() as conn:
                    self.retain_admission(conn, operation_id, admission)
                    conn.commit()
                return
            if row["cancellation_requested"]:
                # The preparation child has succeeded before publication can
                # complete. Its ordinary admission owner proved release.
                self._store_result(
                    _with_report(
                        operation_id,
                        "cancelled",
                        None,
                        result,
                        None
                        if result["preflight"] is None
                        else _mapping(result["preflight"]),
                    )
                )
                return
            try:
                self.daemon._submit(
                    LocalDaemonAdmissionRequest(
                        str(row["queue_item_id"]), cast(str, prepared["run_uri"])
                    ),
                    run_operation_id=operation_id,
                )
            except QueueConflictError:
                self._fail(
                    self._read(operation_id), "admission_conflict", conflict=True
                )

    def cancel_run(self, operation_id: str, principal_id: str) -> LocalDaemonOperation:
        from .local_daemon import _operation_projection

        cancel_id = _cancel_id(operation_id)
        with self.daemon._cycle_lock, self.daemon._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM preparation_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is None or row["kind"] != "run":
                raise QueueConflictError("run operation was not found")
            if row["principal_id"] != principal_id:
                raise QueueConflictError("run operation belongs to another principal")
            old = conn.execute(
                "SELECT * FROM preparation_cancellations WHERE operation_id = ?",
                (cancel_id,),
            ).fetchone()
            if old is not None:
                return self._projection(old)
            if _operation_projection(conn, cancel_id) is not None or (
                self.daemon._execution is not None
                and self.daemon._execution.operation_projection(cancel_id) is not None
            ):
                raise QueueConflictError("cancellation operation identity is ambiguous")
            result = _mapping(json.loads(str(row["result_json"])))
            # Suppression retains actual references; it must not require space
            # for an admission which was refused or will never be created.
            cancel_result: dict[str, PlainData] = {
                "coordinator_id": result["coordinator_id"],
                "target_operation_id": operation_id,
                "queue_item_id": result["queue_item_id"],
                "admission": result["admission"],
                "native_cancellation_operation_id": None,
                "native_control": None,
            }
            operation = _operation(cancel_id, "pending", None, cancel_result)
            result["cancellation_operation_id"] = cancel_id
            projected = _with_report(
                operation_id,
                str(row["state"]),
                row["result_code"],
                result,
                None if result["preflight"] is None else _mapping(result["preflight"]),
            )
            conn.execute(
                "UPDATE preparation_operations SET cancellation_requested = 1, result_json = ? WHERE operation_id = ?",
                (_json(projected.result), operation_id),
            )
            conn.execute(
                "INSERT INTO preparation_cancellations VALUES (?, ?, 'pending', NULL, ?)",
                (cancel_id, operation_id, _json(operation.result)),
            )
            conn.commit()
        self.daemon._wake.set()
        return operation

    def _reconcile_cancellations(self) -> None:
        from .local_daemon import LocalDaemonAdmissionState

        with self.daemon._connection() as conn:
            rows = conn.execute(
                "SELECT rowid AS sequence, * FROM preparation_cancellations "
                "WHERE rowid > ? AND state IN ('pending', 'applying') ORDER BY rowid LIMIT 32",
                (self._cancel_cursor,),
            ).fetchall()
        if not rows:
            self._cancel_cursor = 0
            return
        for control in rows:
            self._cancel_cursor = int(control["sequence"])
            with self.daemon._cycle_lock:
                target = self._read(str(control["target_operation_id"]))
                target_result = _mapping(json.loads(str(target["result_json"])))
                result = _mapping(json.loads(str(control["result_json"])))
                state = "pending"
                if target_result["admission"] is not None:
                    result["admission"] = target_result["admission"]
                    admission = self.daemon._cancel(
                        str(target["queue_item_id"]),
                        principal_id=str(target["principal_id"]),
                    )
                    result["native_cancellation_operation_id"] = (
                        admission.cancellation_operation_id
                    )
                    # Native terminal admission is published only after release.
                    if admission.state in {
                        LocalDaemonAdmissionState.SUCCEEDED,
                        LocalDaemonAdmissionState.FAILED,
                        LocalDaemonAdmissionState.CANCELLED,
                    }:
                        state = "applied"
                    result["native_control"] = {
                        "admission_id": admission.admission_id,
                        "state": admission.state.value,
                        "revision": admission.revision,
                    }
                elif target["state"] in _TERMINAL:
                    state = "applied"
                projected = _operation(
                    str(control["operation_id"]), state, None, result
                )
                with self.daemon._connection() as conn:
                    conn.execute(
                        "UPDATE preparation_cancellations SET state = ?, result_json = ? WHERE operation_id = ?",
                        (state, _json(projected.result), control["operation_id"]),
                    )
                    conn.commit()
