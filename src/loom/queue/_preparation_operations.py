"""Coordinator-owned preparation intent, claims and reconciliation.

Executable composition remains behind the application callbacks. This owner uses
the ordinary admission and assignment owners for all child execution and release
proof, and never holds the daemon's cycle lock during capture or publication.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import Future
from dataclasses import dataclass, replace
from functools import partial
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
from threading import Lock
from time import monotonic
from typing import TYPE_CHECKING, Any, NamedTuple, Protocol, cast

from loom.artifacts import ArtifactRef
from loom.io.uris import uri_to_path
from loom.pipeline.runtime.options import RunOptions
from loom.pipeline.cleanup.preparation_pins import retain_preparation_path
from loom.serialization import PlainData, stable_json_bytes, thaw_plain_data
from loom.runs.context import SubmissionContext

from ._service_signals import write_status
from ._coordinator_transactions import short_write
from ._continuation import ContinuationConflict, ContinuationPending
from .errors import QueueConflictError, QueueServiceError, _PreparationTargetBusy
from .run import RunRequest, _public_operation_id
from ._maintenance import MaintenanceCheckConflict
from ._service_lifetime import ServiceRetiring
from ._phase_timing import PhaseTimings, phase
from .submitted_execution import SubmittedContainerCapability
from .preparation import (
    CANDIDATE_DOCUMENT_ENCODING,
    CANDIDATE_ENCODING_METADATA,
    _candidate_document,
    _read_candidate_document,
    PreparationChildInput,
    PrepareRunRequest,
    SharedInputReceipt,
    StagedInputReceipt,
    capture_shared_input,
    capture_staged_input,
    discard_shared_input_temporaries,
    discard_staged_input_temporaries,
    input_receipt_from_dict,
)

if TYPE_CHECKING:
    from loom.pipeline.status import RunStatus
    from loom.pipeline.stores.read_models import BackendRevision
    from ._managed_local import SQLiteCoordinatorAssignments
    from ._publication_guards import PublicationGuards
    from .managed_local_preparation import ManagedLocalPreparationReceipt
    from .local_daemon import (
        LocalDaemon,
        LocalDaemonAdmission,
        LocalDaemonAdmissionRequest,
        LocalDaemonConfig,
        LocalDaemonOperation,
    )


type _OperationReceipt = tuple[LocalDaemonOperation, bool]
type _SelectedInputs = Callable[[], dict[str, PlainData]]


PREPARATION_RUN_PREFIX = "loom-preparation-"
_MAX_RESULT_BYTES = 64 * 1024
_TERMINAL = frozenset({"applied", "failed", "cancelled", "conflict"})
_LOGGER = logging.getLogger(__name__)


_TERMINAL_CHILD_STATES = frozenset({"SUCCEEDED", "FAILED", "CANCELLED"})


@dataclass(frozen=True, slots=True)
class _ChildReleaseScope:
    coordinator: SQLiteCoordinatorAssignments
    operation_id: str
    principal_id: str
    target_name: str | None
    epoch: str | None
    scheduling_epoch: str | None
    reference_revision: int
    children: tuple[tuple[str, str, int], ...]


@dataclass(frozen=True, slots=True)
class _PendingActionVerification:
    """A native child still in progress; never a result-adoption proof."""

    operation_id: str
    run_uri: str


@dataclass(frozen=True, slots=True)
class _PendingVerificationReport:
    consumer_run_uri: str
    node_id: str
    token: tuple[object, ...]
    future: Future[dict[str, PlainData]]


def _load_verification_report(
    root: Path, reference: ArtifactRef, requested: Mapping[str, PlainData], operation_id: str,
) -> dict[str, PlainData]:
    from loom.pipeline.stores import LocalArtifactStore

    report = _mapping(LocalArtifactStore(root).load(reference))
    if report["action_verification"] != requested or report["operation_id"] != operation_id:
        raise QueueConflictError("action verification retained report conflicts")
    return report


class _InvalidInitialContext(ValueError):
    """Resolved caller annotations cannot be represented within public limits."""


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
    """One checked committed report retained until its publication is admitted."""

    reference: ArtifactRef
    preflight: Mapping[str, PlainData]
    preflight_status: str
    publishable: bool
    prospective_receipt: ManagedLocalPreparationReceipt | None
    publication_data: object
    reconciliation_key: PlainData = None
    action_verification: Mapping[str, PlainData] | None = None


class _ChildIdentity(NamedTuple):
    admission_id: str
    intent_digest: str
    admission_revision: int
    authority_revision: object
    run_status: str


class _ReportIdentity(NamedTuple):
    epoch: str | None
    scheduling_epoch: str | None
    request: str
    selection: str
    child: _ChildIdentity


@dataclass(frozen=True, slots=True)
class _ReadyPublication:
    claim: tuple[object, ...]
    child: _ChildIdentity
    config: LocalDaemonConfig
    request: PrepareRunRequest
    report: PreparationReport
    result: Mapping[str, PlainData]
    publication_owner: str | None


@dataclass(frozen=True, slots=True)
class _PendingPublication:
    ready: _ReadyPublication
    future: Future[ManagedLocalPreparationReceipt]


@dataclass(frozen=True, slots=True)
class _PendingCandidate:
    token: tuple[object, ...]
    report_token: tuple[object, ...]
    report: PreparationReport
    future: Future[dict[str, PlainData]] | None


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

    def capture_candidate(self, config: LocalDaemonConfig, run_uri: str,
                          admission: LocalDaemonAdmission | None) -> dict[str, PlainData]: ...

    def publish_target(
        self,
        config: LocalDaemonConfig,
        request: PrepareRunRequest,
        report: PreparationReport,
    ) -> ManagedLocalPreparationReceipt: ...


class _AuthorityReadPending(Exception):
    """Resume this operation once its bounded authority observation is available."""


class _PublicationChildChanged(Exception):
    """The report's child no longer has the revision that authorized publication."""


def _read_revision_status(config: LocalDaemonConfig, uri: str) -> tuple[BackendRevision, RunStatus]:
    from loom.pipeline.stores.coordinator_authority import _embedded_artifact_reader

    factory = config.coordinator_authority_factory
    assert factory is not None
    # The normal embedded factory opens a complete snapshot to prove existence.
    # The narrow read validates the same selected owner and existing schema itself.
    embedded = _embedded_artifact_reader(factory)
    if embedded is not None:
        return embedded(uri).read_revision_status(uri)
    snapshot = factory(uri).open_run(uri)
    return snapshot.revision, snapshot.status


def _prepare_owned_child(
    guards: PublicationGuards, callbacks: PreparationCallbacks,
    config: LocalDaemonConfig, binding: PreparationChildInput,
    child_name: str, options: RunOptions, owner_id: str,
) -> ManagedLocalPreparationReceipt:
    with guards.hold("preparation-child-" + binding.operation_id):
        retain_preparation_path(config.run_store_root / child_name, coordinator_id=owner_id,
                                operation_id=binding.operation_id)
        return callbacks.prepare_child(config, binding, child_name, options)


def _prepare_path(
    guards: PublicationGuards, operation_id: str, action: str, path: Path,
    owner_id: str, request: PrepareRunRequest,
) -> None:
    with guards.hold("preparation-input-" + operation_id):
        if action == "preparation_target_pin":
            retain_preparation_path(path, coordinator_id=owner_id, operation_id=operation_id)
        elif request.source.mode == "staged":
            discard_staged_input_temporaries(request, artifact_root=path, owner_id=owner_id)
        else:
            discard_shared_input_temporaries(request, snapshot_root=path, owner_id=owner_id)


def _capture_owned_input(
    guards: PublicationGuards, config: LocalDaemonConfig, request: PrepareRunRequest,
    root: Mapping[str, PlainData], owner_id: str,
) -> SharedInputReceipt | StagedInputReceipt:
    with guards.hold("preparation-input-" + request.operation_id):
        if request.source.mode == "staged":
            artifact_root = config.coordinator_root / "preparation-inputs"
            discard_staged_input_temporaries(request, artifact_root=artifact_root, owner_id=owner_id)
            receipt = capture_staged_input(
                request, source_root=Path(cast(str, root["path"])),
                artifact_root=artifact_root, owner_id=owner_id,
            )
            captured_path = uri_to_path(receipt.reference.uri)
        else:
            snapshot_root = Path(cast(str, root["shared_snapshot_root"]))
            discard_shared_input_temporaries(request, snapshot_root=snapshot_root, owner_id=owner_id)
            receipt = capture_shared_input(
                request, source_root=Path(cast(str, root["path"])),
                snapshot_root=snapshot_root, owner_id=owner_id,
            )
            captured_path = snapshot_root / receipt.path
        retain_preparation_path(captured_path, coordinator_id=owner_id, operation_id=request.operation_id)
        return receipt


def _retain_owned_image(
    guards: PublicationGuards, request: PrepareRunRequest,
    roots: Mapping[str, PlainData], owner_id: str,
) -> None:
    from .submitted_execution import retain_submitted_image

    assert request.execution is not None
    with guards.hold("preparation-image-" + request.operation_id):
        retain_submitted_image(
            request.execution.image, roots,
            coordinator_id=owner_id, operation_id=request.operation_id,
        )


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


def _candidate_admission(value: PlainData) -> PlainData:
    if isinstance(value, Mapping) and value.get("state") not in {"FAILED", "SUCCEEDED", "CANCELLED"}:
        # In-flight observations can increment the counter without changing a
        # decision fact. Keep identity, state and cancellation evidence exact;
        # terminal revisions still fence failed-attempt retries.
        return {key: item for key, item in value.items() if key != "revision"}
    return value


def _same_candidate(observed: object, current: Mapping[str, PlainData]) -> bool:
    if isinstance(observed, str):
        observed = thaw_plain_data(_read_candidate_document(observed))
    if not isinstance(observed, Mapping):
        return False
    before, after = dict(observed), dict(current)
    before["admission"] = _candidate_admission(before.get("admission"))
    after["admission"] = _candidate_admission(after.get("admission"))
    return before == after


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
        self._authority_reads: dict[
            str, dict[str, tuple[tuple[object, ...], Future[Any]]]
        ] = {}
        self._child_release_checks: dict[str, tuple[_ChildReleaseScope, Future[bool]]] = {}
        self._verification_reports: dict[str, _PendingVerificationReport] = {}
        self._reports: dict[str, tuple[tuple[object, ...], Future[PreparationReport]]] = {}
        self._target_retries: dict[str, float] = {}
        self._ready_publications: dict[str, _ReadyPublication] = {}
        self._publications: dict[str, _PendingPublication] = {}
        self._candidates: dict[str, _PendingCandidate] = {}
        self._images: dict[str, tuple[tuple[object, ...], Future[None]]] = {}
        self._captures: dict[str, tuple[tuple[object, ...], Future[SharedInputReceipt | StagedInputReceipt]]] = {}
        self._paths: dict[str, tuple[tuple[object, ...], Future[None]]] = {}
        self._admitting: dict[str, tuple[tuple[object, ...], Future[LocalDaemonAdmission]]] = {}
        self._annotations: dict[str, tuple[tuple[object, ...], Future[None]]] = {}
        self._children: dict[str, tuple[tuple[object, ...], Future[ManagedLocalPreparationReceipt]]] = {}

    @property
    def available(self) -> bool:
        return self._available(self.daemon.config)

    def _available(self, config: LocalDaemonConfig) -> bool:
        if self.callbacks is None or not config.preparation_enabled:
            return False
        try:
            self.callbacks.validate_config(config)
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

    def verify_action_result(
        self, *, source_operation_id: str, consumer_run_uri: str, node_id: str,
        contract: Mapping[str, PlainData], candidate: Mapping[str, PlainData],
        timings: PhaseTimings | None = None,
    ) -> dict[str, PlainData] | _PendingActionVerification:
        """Join a replayable installed verifier child to a retained preparation.

        Native action resolution is the sole caller. Reuse the captured input,
        protected installation, dispatch fencing and committed-report owner;
        no public callback endpoint or alternative executor is introduced.
        """
        from dataclasses import replace
        from loom.fingerprints import hash_mapping
        from loom.pipeline._action_verification import action_verification_request
        requested = action_verification_request({"node_id": node_id, "contract": dict(contract), "candidate": dict(candidate)})
        intent = hash_mapping({"source_operation_id": source_operation_id, "request": requested})
        operation_id = "action-verify-" + intent.split(":", 1)[1]
        child_name = PREPARATION_RUN_PREFIX + hashlib.sha256(operation_id.encode()).hexdigest()
        for previous_id, previous in tuple(self._verification_reports.items()):
            if (
                previous.consumer_run_uri == consumer_run_uri and previous.node_id == node_id
                and previous_id != operation_id
            ):
                del self._verification_reports[previous_id]
        pending = _PendingActionVerification(
            operation_id, (self.daemon.config.run_store_root / child_name).as_uri()
        )
        if timings is not None:
            timings.related.update(
                verification_operation_id=operation_id,
                verification_run_uri=pending.run_uri,
            )
        with self.daemon._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM preparation_operations WHERE operation_id = ?", (operation_id,)).fetchone()
            if row is None:
                source = conn.execute("SELECT * FROM preparation_operations WHERE operation_id = ?", (source_operation_id,)).fetchone()
                if source is None:
                    raise QueueConflictError("action verification preparation is unavailable")
                source_result = _mapping(json.loads(str(source["result_json"])))
                if source_result["input_receipt"] is None or source_result["prepared_run"] is None:
                    raise QueueConflictError("action verification requires a published preparation")
                selected = _mapping(json.loads(str(source["selected_json"])))
                selected.pop("reconciliation", None)
                selected["action_verification"] = requested
                request = replace(PrepareRunRequest.from_dict(_mapping(json.loads(str(source["request_json"])))), operation_id=operation_id)
                result: dict[str, PlainData] = {
                    "schema_version": 1, "coordinator_id": source_result["coordinator_id"],
                    "input_receipt": source_result["input_receipt"], "preparation_admission_id": None,
                    "preflight_status": None, "preflight": None, "report_ref": None,
                    "prepared_run": None, "evidence_refs": [],
                }
                write_status(conn, "operation", "INSERT INTO preparation_operations(operation_id, principal_id, kind, intent_digest, request_json, selected_json, target_name, child_name, state, result_json) VALUES (?, ?, 'prepare_run', ?, ?, ?, NULL, ?, 'pending', ?)",
                             (operation_id, source["principal_id"], intent, _json(request.to_dict()), _json(selected), child_name, _json(result)))
                conn.commit()
                self.daemon._wake.set()
                return pending
            if row["intent_digest"] != intent:
                raise QueueConflictError("action verification operation conflicts")
            conn.commit()
        if row["state"] not in _TERMINAL:
            return pending
        if row["state"] != "applied":
            raise QueueConflictError("installed action verification child failed")
        result = _mapping(json.loads(str(row["result_json"])))
        reference = ArtifactRef.from_dict(result["report_ref"])
        token = (
            self.daemon._epoch, self.daemon._scheduling_epoch, consumer_run_uri,
            row["intent_digest"], row["result_json"],
        )
        loading = self._verification_reports.get(operation_id)
        if loading is not None:
            if not loading.future.done():
                return pending
            del self._verification_reports[operation_id]
            if loading.token == token:
                return loading.future.result()
        if len(self._verification_reports) >= 2:
            return pending
        future = self.daemon._result_verifications.bulk.submit(
            operation_id, "action_verification_report_load", _load_verification_report,
            self.daemon.config.run_store_root, reference, requested, operation_id,
        )
        if future is not None:
            self._verification_reports[operation_id] = _PendingVerificationReport(
                consumer_run_uri, node_id, token, future,
            )
        return pending

    def action_verification_pending(self, pending: _PendingActionVerification) -> bool:
        """Observe only native progress; completed children require full resolution."""
        with self.daemon._connection() as conn:
            row = conn.execute(
                "SELECT state FROM preparation_operations WHERE operation_id = ?",
                (pending.operation_id,),
            ).fetchone()
        loading = self._verification_reports.get(pending.operation_id)
        return row is not None and (
            row["state"] not in _TERMINAL
            or (row["state"] == "applied" and loading is not None and not loading.future.done())
        )

    def discard_verification_reports(self, run_uri: str) -> None:
        """Detach cancelled consumers without pretending their IO has stopped."""
        for operation_id, pending in tuple(self._verification_reports.items()):
            if pending.consumer_run_uri == run_uri:
                del self._verification_reports[operation_id]

    def accept_run(
        self, request: RunRequest, principal_id: str
    ) -> LocalDaemonOperation:
        if not isinstance(request, RunRequest):
            raise PreparationNotAccepted("invalid_request", "run request is invalid")
        try:
            return self._accept(
                request.preparation, principal_id, queue_item_id=request.queue_item_id,
                run_mode=request.mode, retry_policy=request.retry_policy,
                fresh_stages=request.fresh_stages,
            )
        except ServiceRetiring:
            raise
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
        except ServiceRetiring:
            raise
        except QueueServiceError as exc:
            code = "invalid_request"
            if (
                "unsupported" in str(exc)
                or "does not support" in str(exc)
                or "requires embedded authority" in str(exc)
            ):
                code = "unsupported"
            raise PreparationNotAccepted(code, str(exc)) from exc

    def _write_public_operation(
        self, operation_id: str,
        apply: Callable[[sqlite3.Connection, _SelectedInputs | None], _OperationReceipt | None],
        *, select: Callable[[LocalDaemonConfig], dict[str, PlainData]] | None = None,
        before_begin: Callable[[], None] | None = None,
        committed: Callable[[_OperationReceipt | None], None] | None = None,
        conflict: str,
    ) -> _OperationReceipt:
        """Resolve external facts for a new receipt; a retained receipt takes precedence."""
        daemon = self.daemon
        sampled = None
        queried = None
        config = daemon.config
        failure: Exception | None = None
        selected: dict[str, PlainData] = {}
        policy = config.sqlite_policy
        deadline = monotonic() + (policy.busy_timeout_ms / 1000 if policy is not None else 30)

        def inputs():
            if failure is not None:
                raise failure
            return selected

        def attempt(conn):
            nonlocal queried, config
            config = daemon.config
            execution = daemon._execution
            queried = (execution, id(config), daemon._epoch, daemon._scheduling_epoch,
                       None if execution is None else execution.slurm_operation_revision)
            return apply(conn, inputs if sampled == queried else None)

        while True:
            receipt = short_write(daemon, attempt, before_begin=before_begin, committed=committed)
            if receipt is not None:
                return receipt
            if sampled is not None and monotonic() >= deadline:
                raise QueueServiceError("operation ownership changed during preparation; retry")
            sampled = queried
            assert sampled is not None
            execution = sampled[0]
            failure = None
            try:
                if execution is not None and execution.slurm_assignments.has_operation(operation_id):
                    raise QueueConflictError(conflict)
                selected = select(config) if select is not None else {}
            except Exception as exc:
                # A matching request may have committed during this read.
                # Apply the failure only to a still-new, current request.
                failure = exc

    def _accept(
        self,
        request: PrepareRunRequest,
        principal_id: str,
        *,
        queue_item_id: str | None = None,
        run_mode: str | None = None,
        retry_policy: str = "never",
        fresh_stages: tuple[str, ...] = (),
    ) -> LocalDaemonOperation:
        from .local_daemon import _operation_projection

        if not isinstance(request, PrepareRunRequest):
            raise QueueServiceError("prepare request is invalid")
        _public_operation_id(request.operation_id)
        kind = "prepare_run" if run_mode is None else "run"
        if request.run_name is None and run_mode != "reconcile":
            raise QueueServiceError("exact preparation requires a target")
        intent = request.intent_digest(principal_id)
        if fresh_stages:
            intent = hashlib.sha256(stable_json_bytes([intent, list(fresh_stages)])).hexdigest()
        if queue_item_id is not None:
            if queue_item_id.startswith(PREPARATION_RUN_PREFIX):
                raise QueueServiceError("run queue identity is reserved")
            intent = hashlib.sha256(
                stable_json_bytes([intent, kind, queue_item_id])
            ).hexdigest()
        if run_mode == "reconcile":
            intent = hashlib.sha256(stable_json_bytes([intent, run_mode, retry_policy])).hexdigest()

        def select(config: LocalDaemonConfig):
            if not self._available(config):
                raise QueueServiceError("preparation is unsupported")
            if request.run_name is not None and request.run_name.startswith(PREPARATION_RUN_PREFIX):
                raise QueueServiceError("preparation target uses a reserved child name")
            policy = config.preparation_policy
            assert policy is not None
            selected = policy.select(request)
            if request.staging_continuation_stages:
                from .shared_execution import stage_scope

                shared = _mapping(selected["profile"]).get("shared_scope")
                if not isinstance(shared, Mapping):
                    raise QueueServiceError("staging continuation requires a protected publication root")
                stage_scope({}, {}, shared, continue_staging=True)
            if fresh_stages:
                from uuid import uuid4

                processor = _mapping(selected["profile"]).get("project_processor")
                if not isinstance(processor, Mapping) or processor.get("schema_version") != 3:
                    raise QueueServiceError("fresh action generation requires installed project capability v3")
                selected["generations"] = {name: uuid4().hex for name in fresh_stages}
            if run_mode == "reconcile":
                processor = _mapping(selected["profile"]).get("project_processor")
                if not isinstance(processor, Mapping) or processor.get("schema_version") != 3:
                    raise QueueServiceError("reconciliation requires installed project capability v3")
                selected["reconciliation"] = {"retry_policy": retry_policy, "publication_owner": None,
                    "candidate": None, "failed_revision": None, "verification_generation": 0}
            selected["run_store_root"] = str(config.run_store_root)
            selected["scheduling"] = scheduling_snapshot(config)
            from loom.pipeline.stores.coordinator_authority import (
                coordinator_authority_identity,
            )

            selected["authority"] = coordinator_authority_identity(
                config.coordinator_authority_factory
            )
            selected["slurm_profiles"] = [
                item.descriptor.to_dict() for item in config.slurm_profiles
            ]
            selected["remote_profiles"] = [
                item.to_dict() for item in config.remote_profiles
            ] if request.execution is None else []
            return selected

        def accept(conn: sqlite3.Connection, inputs):
            coordinator_id = self.daemon._require_started()
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
                conn.execute("DELETE FROM daemon_metadata WHERE key = ?", ("startup-attachment:" + request.operation_id,))
                return self._projection(row), False
            if inputs is None:
                return None
            selected = dict(inputs())
            if _operation_projection(conn, request.operation_id) is not None:
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
                **({"image_retained": False} if request.execution is not None else {}),
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
            if run_mode == "reconcile":
                result.update(queue_item_id=None, admission=None, cancellation_operation_id=None,
                              binding=None, decision=None, verification_report_ref=None)
            from ._maintenance import classify
            full_request = (request.to_dict() if run_mode is None else RunRequest(
                request, queue_item_id, run_mode, retry_policy, fresh_stages).to_dict())
            check = classify(conn, request.operation_id, request=full_request, principal_id=principal_id)
            if check is not None:
                profile_key = "container_capability" if request.execution is not None else "profile_descriptor"
                if _mapping(selected["profile"]).get(profile_key) != check["profile"]:
                    raise QueueConflictError("maintenance check selected profile conflicts")
                selected["maintenance_check"] = dict(check)
            accepted_at = self.daemon._clock()
            result["submission"] = {
                "operation_id": request.operation_id,
                "principal_id": principal_id,
                "accepted_at": accepted_at,
                "context": None if request.context is None else request.context.to_dict(),
            }
            # Reserve enough outer-envelope space to report a terminal failure
            # even for an identifier near the native projection limit.
            _operation(
                request.operation_id, "cancelled", "invalid_preparation_report", result
            )
            operation = _operation(request.operation_id, "pending", None, result)
            write_status(
                conn, "operation",
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
            write_status(conn, "operation", "UPDATE preparation_operations SET accepted_at = ? WHERE operation_id = ?",
                         (accepted_at, request.operation_id))
            # Transfer this bounded startup attachment into the durable native
            # operation in the same acceptance transaction.
            conn.execute("DELETE FROM daemon_metadata WHERE key = ?", ("startup-attachment:" + request.operation_id,))
            return operation, True

        def committed(result: tuple[LocalDaemonOperation, bool] | None) -> None:
            if result is not None and result[1]:
                self.daemon._scheduling_reference_revision += 1

        operation, created = self._write_public_operation(
            request.operation_id, accept, select=select, before_begin=self.daemon._lifetime.require_accepting,
            committed=committed, conflict="managed operation identity is ambiguous",
        )
        if created:
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
                write_status(
                    conn, "operation",
                    "UPDATE preparation_operations SET cancellation_requested = 1 WHERE operation_id = ?",
                    (operation_id,),
                )
                conn.commit()
            operation = self._projection(row)
        self.daemon._wake.set()
        return operation

    def reconcile(self, priorities: tuple[tuple[str, ...], ...] = ()) -> None:
        self.daemon._result_verifications.bulk.reap()
        if self.callbacks is None or not self._reconcile_lock.acquire(blocking=False):
            return
        try:
            now = monotonic()
            self._target_retries = {op: when for op, when in self._target_retries.items() if when > now}
            self._reconcile_cancellations(priorities)
            with self.daemon._connection() as conn:
                for operation_id, pending in tuple(self._verification_reports.items()):
                    admission = conn.execute(
                        "SELECT state FROM managed_admissions WHERE run_uri = ?",
                        (pending.consumer_run_uri,),
                    ).fetchone()
                    if admission is None or admission[0] in {"SUCCEEDED", "FAILED", "CANCELLED", "BLOCKED"}:
                        del self._verification_reports[operation_id]
            for operation_id in tuple(self._ready_publications):
                if self._read(operation_id)["state"] in _TERMINAL:
                    del self._ready_publications[operation_id]
            for operation_id, candidate in tuple(self._candidates.items()):
                if (candidate.future is None or candidate.future.done()) and self._read(operation_id)["state"] in _TERMINAL:
                    del self._candidates[operation_id]
            for pending in (self._reports, self._children, self._images, self._paths, self._admitting, self._annotations):
                for operation_id, (_, future) in tuple(pending.items()):
                    if future.done() and self._read(operation_id)["state"] in _TERMINAL:
                        del pending[operation_id]
            rows, self._cursor = self._pending_page("preparation", self._cursor, priorities)
            for row in rows:
                try:
                    self._advance(row)
                except MaintenanceCheckConflict:
                    self._fail(self._read(str(row["operation_id"])), "maintenance_check_constraints", conflict=True)
                except _InvalidInitialContext:
                    self._fail(self._read(str(row["operation_id"])), "invalid_context")
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

    def _pending_page(
        self, owner: str, cursor: int, priorities: tuple[tuple[str, ...], ...],
    ) -> tuple[tuple[sqlite3.Row, ...], int]:
        table = "preparation_operations" if owner == "preparation" else "preparation_cancellations"
        columns = "*" if owner == "preparation" else "operation_id"
        query = f"SELECT rowid AS sequence, {columns} FROM {table} WHERE state IN ('pending', 'applying')"
        with self.daemon._connection() as conn:
            page = conn.execute(query + " AND rowid > ? ORDER BY rowid LIMIT 32", (cursor,)).fetchall()
            page_rows = {row["operation_id"]: row for row in page}
            selected: dict[str, sqlite3.Row] = {}
            for scope in priorities:
                if len(scope) != 2 or scope[0] != owner:
                    continue
                operation_id = scope[1]
                row = page_rows.get(operation_id)
                if row is None:
                    row = conn.execute(query + " AND operation_id = ?", (operation_id,)).fetchone()
                if row is None:
                    self.daemon._result_verifications.bulk.discard(scope)
                    if owner == "preparation":
                        self._authority_reads.pop(operation_id, None)
                else:
                    selected[operation_id] = row
        selected.update(page_rows)
        return tuple(selected.values()), page[-1]["sequence"] if page else 0

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

    def _store_result(self, operation: LocalDaemonOperation, *, claim=None) -> bool:
        with self.daemon._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                "SELECT * FROM preparation_operations WHERE operation_id = ?",
                (operation.operation_id,),
            ).fetchone()
            if claim is not None and (current is None or current["state"] != "applying"
                                      or self._publication_token(current) != claim):
                return False
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
            result_json = _json(operation.result)
            changed = current is not None and (current["state"], current["result_code"], current["result_json"]) != (
                operation.state, operation.code, result_json,
            )
            write_status(
                conn, "operation",
                "UPDATE preparation_operations SET state = ?, result_code = ?, result_json = ? WHERE operation_id = ?",
                (operation.state, operation.code, result_json, operation.operation_id),
            )
            conn.commit()
        if changed and operation.state not in _TERMINAL:
            self.daemon._result_verifications.bulk.resume(("preparation", operation.operation_id))
        else:
            self.daemon._wake.set()
        return True

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

    def _configuration(self, selected: Mapping[str, PlainData], request: PrepareRunRequest) -> LocalDaemonConfig:
        from loom.pipeline.stores.coordinator_authority import (
            coordinator_authority_identity,
        )

        execution = self.daemon._execution
        if execution is None:
            raise PreparationConfigurationUnavailable(
                "preparation execution owner is unavailable"
            )
        with self.daemon._state_guard():
            config = self.daemon.config
            available = tuple(execution.slurm_profiles.values())
            components = execution.preparation_scheduling_components(_mapping(selected["scheduling"]))
        from .preparation import _local_scope, _require_local_binding

        scope = _local_scope(_mapping(selected["profile"]).get("local_scope"))
        try:
            _require_local_binding(scope, config.resident_worker_launch_profile,
                                   agent_id=config.machine_id)
        except QueueConflictError as exc:
            raise PreparationConfigurationUnavailable("accepted local preparation binding is unavailable") from exc
        if (
            coordinator_authority_identity(
                config.coordinator_authority_factory
            )
            != selected["authority"]
        ):
            raise PreparationConfigurationUnavailable(
                "accepted preparation authority is unavailable"
            )
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
                    for item in config.remote_profiles
                    if item.to_dict() == descriptor
                ),
                None,
            )
            if remote is None:
                raise PreparationConfigurationUnavailable(
                    "accepted preparation remote profile is unavailable"
                )
            remote_profiles.append(remote)
        capability_data = _mapping(selected["profile"]).get("container_capability")
        capabilities = config.container_capabilities
        if capability_data is not None:
            retained_capability = SubmittedContainerCapability.from_dict(capability_data)
            from .submitted_execution import SELECTED_INPUT_WORKER_CONTRACT
            dynamic = request.execution is not None and request.execution.worker_contract == SELECTED_INPUT_WORKER_CONTRACT
            capabilities = tuple(
                item for item in capabilities if (
                    item.permits(retained_capability) if dynamic else item.to_dict() == capability_data
                )
            )
            if not capabilities:
                raise PreparationConfigurationUnavailable(
                    "accepted container execution policy is unavailable"
                )
        return replace(
            config,
            run_store_root=Path(cast(str, selected["run_store_root"])),
            scheduling_components=components,
            slurm_profiles=tuple(profiles),
            remote_profiles=tuple(remote_profiles),
            container_capabilities=capabilities,
        )

    def _advance(self, row: sqlite3.Row) -> None:
        operation_id = str(row["operation_id"])
        scope = ("preparation", operation_id)
        bulk = self.daemon._result_verifications.bulk
        try:
            with bulk.offering(scope):
                self._advance_owned(row)
        except _AuthorityReadPending:
            # A second observation may depend on the first. Retain both until
            # the scheduler can reach the waiting action.
            return
        except Exception:
            self._authority_reads.pop(operation_id, None)
            raise
        if operation_id in self._authority_reads and not bulk.scopes(scope):
            # Once the action runs, its completion needs a fresh observation.
            self._authority_reads.pop(operation_id, None)

    def _advance_owned(self, row: sqlite3.Row) -> None:
        from .local_daemon import LocalDaemonAdmissionRequest, LocalDaemonAdmissionState

        callbacks = self.callbacks
        assert callbacks is not None
        operation_id = str(row["operation_id"])
        # Another caller may have cancelled after this reconciliation page was
        # selected. Only this reconciler mutates execution/publication progress.
        row = self._read(operation_id)
        if row["state"] in _TERMINAL:
            pending = self._publications.get(operation_id)
            if pending is not None and pending.future.done():
                del self._publications[operation_id]
            return
        if (row["dispatch_claimed"] and row["child_admission_id"] is None
                and row["cancellation_requested"]):
            # Cancellation and insertion race under the same SQLite writer. An
            # already committed child must rejoin its ordinary release owner.
            with self.daemon._connection() as conn:
                changed = write_status(
                    conn, "operation", "UPDATE preparation_operations SET dispatch_claimed=0 "
                    "WHERE operation_id=? AND child_admission_id IS NULL AND dispatch_claimed=1 "
                    "AND cancellation_requested=1 AND NOT EXISTS "
                    "(SELECT 1 FROM managed_admissions WHERE queue_item_id=preparation_operations.child_name)",
                    (operation_id,),
                ).rowcount
                conn.commit()
            if changed:
                return
        if self._complete_publication(row) or self._advance_ready_publication(row):
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
            pending_image = self._images.get(operation_id)
            if pending_image is not None:
                if not pending_image[1].done():
                    return
                del self._images[operation_id]
                try:
                    pending_image[1].result()
                    result["image_retained"] = True
                except (QueueServiceError, OSError):
                    pass
            pending_capture = self._captures.get(operation_id)
            if pending_capture is not None:
                if not pending_capture[1].done():
                    return  # Never remove temporary files beneath a running capture.
                del self._captures[operation_id]
                try:
                    result["input_receipt"] = pending_capture[1].result().to_dict()
                except (QueueServiceError, OSError):
                    pass  # Cancellation owns cleanup of this finished failed capture.
            if result["input_receipt"] is None:
                root = (self.daemon.config.coordinator_root / "preparation-inputs"
                        if request.source.mode == "staged" else
                        Path(cast(str, _mapping(selected["source_root"])["shared_snapshot_root"])))
                if not self._path_ready(row, request, root, "preparation_input_cleanup"):
                    return
            self._store_result(_operation(operation_id, "cancelled", None, result))
            return
        config = self._configuration(selected, request)
        profile = _mapping(selected["profile"])
        receipt_data = result["input_receipt"]
        if receipt_data is None:
            root = _mapping(selected["source_root"])
            try:
                receipt = self._capture_input_async(row, config, request, root)
                if receipt is None:
                    return
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
        if request.execution is not None and not result.get("image_retained"):
            try:
                if not self._retain_image_async(row, request, _mapping(profile["image_roots"])):
                    return
                result["image_retained"] = True
                self._store_result(_operation(operation_id, "pending", None, result))
            except (QueueServiceError, OSError):
                self._fail(row, "image_unavailable")
                return
        from .preparation import _project_target_uri

        project_binding = None
        if profile.get("project_processor") is not None:
            try:
                project_binding = {
                    "processor": profile["project_processor"],
                    "target_run_uri": None if request.run_name is None else _project_target_uri(config.run_store_root, request.run_name),
                    **({"run_store_root_uri": _project_target_uri(config.run_store_root.parent, config.run_store_root.name)} if request.run_name is None else {}),
                }
            except QueueConflictError:
                self._fail(row, "publication_conflict", conflict=True)
                return
        candidate = _mapping(selected["reconciliation"])["candidate"] if "reconciliation" in selected else None
        binding = PreparationChildInput(
            request.operation_id,
            request.preparation_profile,
            request.config_path,
            receipt,
            None if request.execution is not None else _mapping(profile["profile_descriptor"]),
            request.overlays,
            request.overrides,
            request.run_options,
            cast(Mapping[str, PlainData] | None, profile.get("local_scope")),
            project_binding,
            cast(Mapping[str, PlainData] | None, None if isinstance(candidate, str) else candidate),
            _candidate_document=candidate if isinstance(candidate, str) else None,
            shared_scope=cast(Mapping[str, PlainData] | None, profile.get("shared_scope")),
            generations=cast(Mapping[str, str] | None, selected.get("generations")),
            action_verification=cast(Mapping[str, PlainData] | None, selected.get("action_verification")),
            execution=request.execution,
            staging_continuation_stages=request.staging_continuation_stages,
            container_capability=(
                SubmittedContainerCapability.from_dict(profile["container_capability"])
                if request.execution is not None else None
            ),
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
                    child_claim = self._publication_token(row)
                    child_receipt = self._prepare_child_async(
                        row, config, binding, child_name,
                        RunOptions.from_dict(profile["runtime_options"]),
                    )
                    if child_receipt is None:
                        return
                except (QueueServiceError, QueueConflictError):
                    self._fail(row, "preparation_child_failed")
                    return
                child_uri = child_receipt.run_uri
                def claim_child(conn):
                    current = conn.execute(
                        "SELECT * FROM preparation_operations WHERE operation_id = ?",
                        (operation_id,),
                    ).fetchone()
                    assert current is not None
                    if current["cancellation_requested"] or self._publication_token(current) != child_claim:
                        return False
                    write_status(
                        conn, "operation",
                        "UPDATE preparation_operations SET dispatch_claimed = 1 WHERE operation_id = ?",
                        (operation_id,),
                    )
                    return True
                if not short_write(self.daemon, claim_child):
                    return
            else:
                from loom.pipeline.stores import path_to_run_uri

                # The durable dispatch claim proves child publication completed.
                # Its admission may already have run after a lost submit reply;
                # rejoin that admission without replanning an executed child.
                child_uri = path_to_run_uri(config.run_store_root / child_name)
            admission = self._submit_async(row, LocalDaemonAdmissionRequest(child_name, child_uri), child=True)
            if admission is None:
                return
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
                write_status(
                    conn, "operation",
                    "UPDATE preparation_operations SET child_admission_id = ?, result_json = ? WHERE operation_id = ?",
                    (admission.admission_id, _json(projected.result), operation_id),
                )
                conn.commit()
            row = self._read(operation_id)
        if row["cancellation_requested"] and row["state"] == "pending":
            self._advance_child_release(operation_id, self._cancel_child)
            return
        admission = self.daemon._admission(str(row["child_admission_id"]))
        if admission.state in {
            LocalDaemonAdmissionState.FAILED,
            LocalDaemonAdmissionState.CANCELLED,
        }:
            self._fail(row, "preparation_child_failed")
            return
        if admission.state is not LocalDaemonAdmissionState.SUCCEEDED:
            return
        try:
            report_job = self._reports.get(operation_id)
            candidate_job = self._candidates.get(operation_id)
            if report_job is not None and not report_job[1].done():
                return
            if candidate_job is not None and candidate_job.future is not None and not candidate_job.future.done():
                return
            report_token = self._report_token(row, config, admission)
            # Admission can settle before the child authority records run.completed.
            # Hydrating its report at that prior revision forces a second render.
            if report_token.child.run_status != "SUCCEEDED":
                if report_token.child.run_status in {"FAILED", "CANCELLED", "INTERRUPTED"}:
                    self._fail(row, "preparation_child_failed")
                return
            report = self._read_report_async(row, config, admission, request, binding, report_token)
            if report is None:
                return
            if "reconciliation" in selected:
                references = cast(list[PlainData], result["evidence_refs"])
                if not references:
                    references.append({"preparation_admission_id": result["preparation_admission_id"], "report_ref": report.reference.to_dict()})
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
        if report.action_verification is not None:
            # The committed verifier report is the terminal output of this
            # internal preparation child; it never publishes another target.
            self._store_result(_with_report(operation_id, "applied", None, result, report.preflight))
            return
        if not report.publishable:
            self._store_result(
                _with_report(
                    operation_id, "failed", "preflight_failed", result, report.preflight
                )
            )
            return
        assert report.prospective_receipt is not None
        if "reconciliation" in selected:
            self._reconcile_target(row, request, selected, config, report, result, report_token)
            return
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
            target_claim = self._publication_token(row)
            if not self._path_ready(row, request, config.run_store_root / cast(str, request.run_name),
                                    "preparation_target_pin"):
                return
            def claim_target(conn):
                current = conn.execute("SELECT * FROM preparation_operations WHERE operation_id=?",
                                       (operation_id,)).fetchone()
                if self._publication_token(current) != target_claim:
                    return False
                return write_status(
                    conn, "operation",
                    "UPDATE preparation_operations SET state = 'applying', result_json = ? WHERE operation_id = ? AND state = 'pending' AND cancellation_requested = 0",
                    (_json(projected.result), operation_id),
                ).rowcount
            claimed = short_write(self.daemon, claim_target)
            if not claimed:
                return
        self._publish_async(config, request, report, result, report_token, str(row["selected_json"]), publication_owner=None)

    def _save_selection(self, operation_id: str, selected: Mapping[str, PlainData]) -> None:
        with self.daemon._connection() as conn:
            write_status(conn, "operation", "UPDATE preparation_operations SET selected_json = ? WHERE operation_id = ?",
                         (_json(selected), operation_id))
            conn.commit()

    def _reconcile_target(self, row: sqlite3.Row, request: PrepareRunRequest,
                          selected: dict[str, PlainData], config: LocalDaemonConfig,
                          report: PreparationReport, result: dict[str, PlainData], report_token: _ReportIdentity) -> None:
        from loom.pipeline.stores import run_uri_to_path
        from .local_daemon import AdmissionNotFoundError

        assert self.callbacks is not None and report.prospective_receipt is not None
        operation_id = str(row["operation_id"])
        uri = report.prospective_receipt.run_uri
        target_name = run_uri_to_path(uri).name
        reconciliation = _mapping(selected["reconciliation"])
        selected["reconciliation"] = reconciliation
        row = self._read(operation_id)
        if row["cancellation_requested"]:
            self._store_result(_with_report(operation_id, "cancelled", None, result, report.preflight))
            return
        resume_cancelled = reconciliation["retry_policy"] == "one_observed_cancellation"
        if row["target_name"] is None:
            if resume_cancelled:
                # A continuation cannot become the publication owner of a new run.
                try:
                    self.daemon.admission_for_run_uri(uri)
                except AdmissionNotFoundError:
                    self._fail(row, "cancelled_admission_missing", conflict=True)
                    return
            target_claim = self._publication_token(row)
            if not self._path_ready(row, request, config.run_store_root / target_name, "preparation_target_pin"):
                return
            with self.daemon._connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                current = conn.execute("SELECT * FROM preparation_operations WHERE operation_id = ?", (operation_id,)).fetchone()
                if current["cancellation_requested"] or self._publication_token(current) != target_claim:
                    return
                if "cancellation_operation_id" in result:
                    result["cancellation_operation_id"] = json.loads(current["result_json"])["cancellation_operation_id"]
                owners = conn.execute("SELECT * FROM preparation_operations WHERE target_name = ? ORDER BY rowid", (target_name,)).fetchall()
                owner = owners[0] if owners else None
                if owner is not None:
                    previous = _mapping(json.loads(str(owner["selected_json"])))
                    previous.pop("reconciliation", None)
                    scope = dict(selected)
                    scope.pop("reconciliation", None)
                    old_request = PrepareRunRequest.from_dict(json.loads(str(owner["request_json"])))
                    if owner["principal_id"] != row["principal_id"] or previous != scope or (old_request.source.root, old_request.source.path) != (request.source.root, request.source.path):
                        conn.rollback()
                        self._fail(row, "candidate_scope_conflict", conflict=True)
                        return
                queue_id = target_name if owner is None else owner["queue_item_id"] or target_name
                reconciliation["publication_owner"] = operation_id if owner is None else str(owner["operation_id"])
                result["queue_item_id"] = queue_id
                try:
                    self._check_run_budget(operation_id, {**result, "prepared_run": report.prospective_receipt.to_dict()})
                except _ResultTooLarge:
                    conn.rollback()
                    self._fail(row, "result_too_large")
                    return
                write_status(conn, "operation", "UPDATE preparation_operations SET target_name = ?, queue_item_id = ?, selected_json = ?, result_json = ? WHERE operation_id = ?",
                             (target_name, queue_id, _json(selected), _json(result), operation_id))
                conn.commit()
            row = self._read(operation_id)
        elif row["target_name"] != target_name:
            self._fail(row, "candidate_key_conflict", conflict=True)
            return
        else:
            # Binding and cancellation receipts are retained independently of child reports.
            retained = _mapping(json.loads(str(row["result_json"])))
            result["queue_item_id"], result["binding"] = retained["queue_item_id"], retained["binding"]
        owner = self._read(cast(str, reconciliation["publication_owner"]))
        if (owner["cancellation_requested"] and owner["state"] != "applied") or owner["state"] in {"failed", "cancelled", "conflict"}:
            self._fail(row, "candidate_publication_failed", conflict=True)
            return
        if owner["operation_id"] != operation_id and owner["state"] != "applied":
            return
        try:
            admission = self.daemon.admission_for_run_uri(uri)
        except AdmissionNotFoundError:
            admission = None
        if resume_cancelled and admission is None:
            self._fail(row, "cancelled_admission_missing", conflict=True)
            return
        if admission is not None:
            if admission.queue_item_id != row["queue_item_id"]:
                self._fail(row, "candidate_admission_conflict", conflict=True)
                return
            if admission.state.value in {"CANCELLATION_REQUESTED", "CANCELLING"}:
                if not resume_cancelled:
                    self._fail(row, "candidate_cancellation_pending", conflict=True)
                return
            if (admission.state.value == "CANCELLED" or admission.cancellation_operation_id is not None) and not resume_cancelled:
                self._fail(row, "candidate_cancelled", conflict=True)
                return
            if reconciliation["retry_policy"] != "never" and admission.state.value != "SUCCEEDED":
                execution = self.daemon._execution
                if execution is None:
                    return
                admission_identity = (admission.admission_id, admission.intent_digest, admission.revision)
                outcome = execution.settle_continuation(
                    admission, accepted_at=row["accepted_at"],
                    observe_snapshot=lambda assignments, read: self._observe_authority(
                        row, uri, "preparation_slurm_retry_authority_read", (*admission_identity, assignments), read,
                    ),
                )
                if isinstance(outcome, ContinuationConflict):
                    self._fail(row, outcome.reason, conflict=True)
                    return
                if isinstance(outcome, ContinuationPending):
                    if row["result_code"] != outcome.reason:
                        self._store_result(_with_report(operation_id, "pending", outcome.reason, result, report.preflight))
                    return
                admission = self.daemon.admission_for_run_uri(uri)
            if resume_cancelled:
                observed = reconciliation.get("cancelled_revision")
                if admission.state.value != "CANCELLED" or (observed is not None and (
                    observed != admission.revision or
                    reconciliation.get("cancellation_operation_id") != admission.cancellation_operation_id
                )):
                    self._fail(row, "cancelled_revision_conflict", conflict=True)
                    return
                if observed is None:
                    reconciliation["cancelled_revision"] = admission.revision
                    reconciliation["cancellation_operation_id"] = admission.cancellation_operation_id
                    self._save_selection(operation_id, selected)
        path = run_uri_to_path(uri)
        if admission is None and not path.exists() and not path.is_symlink() and owner["operation_id"] == operation_id and row["state"] == "pending":
            # Only the selected owner can publish; cancellation still fences admission.
            self._store_result(_with_report(operation_id, "applying", None, result, report.preflight))
            publish = True
        else:
            publish = False
        if not publish:
            if owner["operation_id"] == operation_id and row["state"] == "applying" and reconciliation["candidate"] is None:
                # The original publisher alone may reconcile a lost publication reply.
                publish = True
            else:
                try:
                    candidate = self._capture_candidate_async(row, config, uri, admission, report, report_token)
                    if candidate is None:
                        return
                except _AuthorityReadPending:
                    raise
                except Exception:
                    self._fail(row, "candidate_unavailable", conflict=True)
                    return
                if reconciliation["failed_revision"] is None and admission is not None and admission.state.value == "FAILED":
                    if reconciliation["retry_policy"] != "one_observed_failure":
                        self._fail(row, "candidate_failed", conflict=True)
                        return
                    reconciliation["failed_revision"] = admission.revision
                    self._save_selection(operation_id, selected)
                if not _same_candidate(reconciliation["candidate"], candidate):
                    # A new verifier may use the scalar form only when the selected
                    # worker has advertised its decoder. A retained generation owns
                    # its original encoding across coordinator restarts.
                    reconciliation["candidate"] = (
                        _candidate_document(candidate)
                        if report.reference.metadata.get(CANDIDATE_ENCODING_METADATA) == CANDIDATE_DOCUMENT_ENCODING
                        else candidate
                    )
                    reconciliation["verification_generation"] = cast(int, reconciliation["verification_generation"]) + 1
                    generation = reconciliation["verification_generation"]
                    child_name = PREPARATION_RUN_PREFIX + hashlib.sha256(f"{operation_id}:verify:{generation}".encode()).hexdigest()
                    with self.daemon._connection() as conn:
                        conn.execute("BEGIN IMMEDIATE")
                        current = conn.execute("SELECT result_json FROM preparation_operations WHERE operation_id = ?", (operation_id,)).fetchone()
                        result["cancellation_operation_id"] = json.loads(current["result_json"])["cancellation_operation_id"]
                        write_status(conn, "operation", "UPDATE preparation_operations SET selected_json = ?, child_name = ?, child_admission_id = NULL, dispatch_claimed = 0, state = 'pending', result_code = NULL, result_json = ? WHERE operation_id = ?",
                                     (_json(selected), child_name, _json(result), operation_id))
                        conn.commit()
                    self.daemon._result_verifications.bulk.resume(("preparation", operation_id))
                    return
                # read_report checked a committed installed verifier against this pinned input.
                if reconciliation["verification_generation"] == 0:
                    raise QueueConflictError("candidate verifier is missing")
                result["verification_report_ref"] = report.reference.to_dict()
                result["binding"] = {"run_uri": uri, "publication_operation_id": reconciliation["publication_owner"]}
                result["prepared_run"] = candidate["prepared_run"]
                result["decision"] = "retry" if reconciliation["failed_revision"] is not None or reconciliation.get("cancelled_revision") is not None else "reuse" if admission is not None and admission.state.value == "SUCCEEDED" else "observe" if admission is not None else "admit_prepared"
                self._store_result(_with_report(operation_id, "applying", None, result, report.preflight))
                self._continue_run(self._read(operation_id))
                return
        # Publication retains its exact identity; a cancellation accepted during
        # IO suppresses subsequent admission in the final native transaction.
        self._publish_async(
            config, replace(request, run_name=target_name), report, result, report_token, _json(selected),
            publication_owner=cast(str, reconciliation["publication_owner"]),
        )

    def _report_token(
        self,
        row: sqlite3.Row,
        config: LocalDaemonConfig,
        admission: LocalDaemonAdmission,
    ) -> _ReportIdentity:
        return _ReportIdentity(
            self.daemon._epoch,
            self.daemon._scheduling_epoch,
            row["request_json"],
            row["selected_json"],
            self._child_token(row, config, admission),
        )

    def _observe_authority[T](
        self, row: sqlite3.Row, uri: str, action: str, identity: tuple[object, ...], read: Callable[[], T],
    ) -> T:
        operation_id = str(row["operation_id"])
        reads = self._authority_reads.setdefault(operation_id, {})
        key = (*self._publication_token(row), row["state"], row["cancellation_requested"], uri, *identity)
        previous = reads.get(action)
        if previous is not None and previous[0] == key:
            future = previous[1]
            if not future.done():
                raise _AuthorityReadPending
            try:
                return future.result()
            except Exception:
                del reads[action]
                raise
        future = self.daemon._result_verifications.bulk.submit(
            operation_id, action, read,
        )
        if future is not None:
            reads[action] = key, future
        raise _AuthorityReadPending

    def _child_token(
        self, row: sqlite3.Row, config: LocalDaemonConfig, admission: LocalDaemonAdmission,
    ) -> _ChildIdentity:
        identity = (admission.admission_id, admission.intent_digest, admission.revision)
        revision, status = self._observe_authority(
            row, admission.run_uri, "preparation_child_authority_read", identity,
            partial(_read_revision_status, config, admission.run_uri),
        )
        return _ChildIdentity(*identity, revision, status.value)

    def _capture_candidate_async(
        self, row: sqlite3.Row, config: LocalDaemonConfig, uri: str,
        admission: LocalDaemonAdmission | None, report: PreparationReport, report_token: _ReportIdentity,
    ) -> dict[str, PlainData] | None:
        operation_id = str(row["operation_id"])
        assert self.callbacks is not None
        admission_identity = _candidate_admission(None if admission is None else admission.to_dict())
        revision, _ = self._observe_authority(
            row, uri, "preparation_candidate_authority_read", (admission_identity, report_token),
            partial(_read_revision_status, config, uri),
        )
        token = (*self._publication_token(row), uri, admission_identity, revision, report_token)
        pending = self._candidates.get(operation_id)
        if pending is not None and pending.future is not None:
            if not pending.future.done():
                return None
            del self._candidates[operation_id]
            if pending.token == token:
                return pending.future.result()
        if operation_id not in self._candidates and len(self._candidates) >= 2:
            return None
        future = self.daemon._result_verifications.bulk.submit(
            operation_id, "preparation_candidate_inspection",
            self.callbacks.capture_candidate, config, uri, admission,
        )
        # Keep the admitted report only for this inspection operation, including
        # capacity waits. Do not rehydrate it on every reconciliation turn.
        self._reports.pop(operation_id, None)
        self._candidates[operation_id] = _PendingCandidate(
            token, report_token, report, future,
        )
        return None

    def _retain_image_async(
        self, row: sqlite3.Row, request: PrepareRunRequest, roots: Mapping[str, PlainData],
    ) -> bool:
        operation_id = str(row["operation_id"])
        token = self._publication_token(row)
        pending = self._images.get(operation_id)
        if pending is not None:
            previous, future = pending
            if not future.done():
                return False
            del self._images[operation_id]
            if previous == token:
                future.result()
                return True
        if len(self._images) >= 2:
            return False
        future = self.daemon._result_verifications.bulk.submit(
            operation_id, "preparation_image_retention", _retain_owned_image,
            self.daemon._publication_guards, request, dict(roots), self.daemon._require_started(),
        )
        if future is not None:
            self._images[operation_id] = (token, future)
        return False

    def _capture_input_async(
        self, row: sqlite3.Row, config: LocalDaemonConfig,
        request: PrepareRunRequest, root: Mapping[str, PlainData],
    ) -> SharedInputReceipt | StagedInputReceipt | None:
        operation_id = str(row["operation_id"])
        token = self._publication_token(row)
        pending = self._captures.get(operation_id)
        if pending is not None:
            previous, future = pending
            if not future.done():
                return None
            del self._captures[operation_id]
            if previous == token:
                return future.result()
        if len(self._captures) >= 2:
            return None
        future = self.daemon._result_verifications.bulk.submit(
            operation_id, "preparation_input_capture", _capture_owned_input,
            self.daemon._publication_guards, config, request, dict(root),
            self.daemon._require_started(),
        )
        if future is not None:
            self._captures[operation_id] = (token, future)
        return None

    def next_target_delay(self) -> float | None:
        deadlines = tuple(self._target_retries.values())
        return max(0.0, min(deadlines) - monotonic()) if deadlines else None

    def _target_retry_ready(self, operation_id: str) -> bool:
        deadline = self._target_retries.get(operation_id)
        if deadline is None:
            return True
        if monotonic() < deadline:
            return False
        del self._target_retries[operation_id]
        return True

    def _path_ready(self, row: sqlite3.Row, request: PrepareRunRequest, path: Path, action: str) -> bool:
        operation_id = request.operation_id
        token = (*self._publication_token(row), path, action)
        pending = self._paths.get(operation_id)
        if pending is not None:
            previous, future = pending
            if not future.done():
                return False
            del self._paths[operation_id]
            if previous == token:
                future.result()
                return True
        future = self.daemon._result_verifications.bulk.submit(
            operation_id, action, _prepare_path, self.daemon._publication_guards,
            operation_id, action, path, self.daemon._require_started(), request,
        )
        if future is not None:
            self._paths[operation_id] = (token, future)
        return False

    def _prepare_child_async(
        self, row: sqlite3.Row, config: LocalDaemonConfig,
        binding: PreparationChildInput, child_name: str, options: RunOptions,
    ) -> ManagedLocalPreparationReceipt | None:
        operation_id = str(row["operation_id"])
        token = (*self._publication_token(row), child_name)
        pending = self._children.get(operation_id)
        if pending is not None:
            previous, future = pending
            if not future.done():
                return None
            del self._children[operation_id]
            if previous == token:
                try:
                    return future.result()
                except _PreparationTargetBusy:
                    self._target_retries[operation_id] = monotonic() + 0.1
                    return None
        if not self._target_retry_ready(operation_id) or len(self._children) >= 2:
            return None
        assert self.callbacks is not None
        future = self.daemon._result_verifications.bulk.submit(
            operation_id, "preparation_child_construction", _prepare_owned_child,
            self.daemon._publication_guards, self.callbacks, config, binding,
            child_name, options, self.daemon._require_started(),
        )
        if future is not None:
            self._children[operation_id] = (token, future)
        return None

    def _publication_token(self, row: sqlite3.Row) -> tuple[object, ...]:
        return (
            self.daemon._epoch, self.daemon._scheduling_epoch,
            row["request_json"], row["selected_json"], row["child_admission_id"],
            row["target_name"],
        )

    def _publish_async(
        self,
        config: LocalDaemonConfig,
        request: PrepareRunRequest,
        report: PreparationReport,
        result: Mapping[str, PlainData],
        report_token: _ReportIdentity,
        selected_json: str,
        *,
        publication_owner: str | None,
    ) -> None:
        row = self._read(request.operation_id)
        claim = self._publication_token(row)
        # Only this reconciler selects the owner. Check its exact committed
        # selection together with the identities that authorized validation.
        if (
            report_token.epoch != self.daemon._epoch
            or report_token.scheduling_epoch != self.daemon._scheduling_epoch
            or report_token.request != row["request_json"]
            or selected_json != row["selected_json"]
        ):
            return
        self._reports.pop(request.operation_id, None)
        self._ready_publications[request.operation_id] = _ReadyPublication(
            claim,
            report_token.child,
            config,
            request,
            report,
            dict(result),
            publication_owner,
        )
        self._advance_ready_publication(row)

    def _publish_owned_target(
        self, ready: _ReadyPublication, child_uri: str,
    ) -> ManagedLocalPreparationReceipt:
        assert self.callbacks is not None
        operation_id = ready.request.operation_id
        with self.daemon._publication_guards.hold("preparation-" + operation_id):
            revision, status = _read_revision_status(ready.config, child_uri)
            row = self._read(operation_id)
            # A read on another store can outlive cancellation, reload or a new
            # admission revision. Only the exact durable claim can publish.
            if (row["state"] != "applying" or ready.claim != self._publication_token(row)
                    or (ready.publication_owner is not None and row["cancellation_requested"])):
                raise _PublicationChildChanged
            admission = self.daemon._admission(str(row["child_admission_id"]))
            if ready.child != _ChildIdentity(
                admission.admission_id, admission.intent_digest, admission.revision, revision, status.value,
            ):
                raise _PublicationChildChanged
            return self.callbacks.publish_target(ready.config, ready.request, ready.report)

    def _advance_ready_publication(self, row: sqlite3.Row) -> bool:
        operation_id = str(row["operation_id"])
        ready = self._ready_publications.get(operation_id)
        if ready is None:
            return False
        if (
            row["state"] != "applying"
            or ready.claim != self._publication_token(row)
            or (ready.publication_owner is not None and row["cancellation_requested"])
        ):
            del self._ready_publications[operation_id]
            return False
        if not self._target_retry_ready(operation_id) or len(self._publications) >= 2:
            return True
        admission = self.daemon._admission(str(row["child_admission_id"]))
        if ready.child[:3] != (admission.admission_id, admission.intent_digest, admission.revision):
            del self._ready_publications[operation_id]
            return False
        future = self.daemon._result_verifications.bulk.submit(
            operation_id, "preparation_target_publication", self._publish_owned_target,
            ready, admission.run_uri,
        )
        if future is not None:
            self._publications[operation_id] = _PendingPublication(ready, future)
            del self._ready_publications[operation_id]
        return True

    def _complete_publication(self, row: sqlite3.Row) -> bool:
        operation_id = str(row["operation_id"])
        pending = self._publications.get(operation_id)
        if pending is None:
            return False
        annotation = self._annotations.get(operation_id)
        if not pending.future.done() or (annotation is not None and not annotation[1].done()):
            return True
        ready = pending.ready
        if (row["state"] != "applying" or ready.claim != self._publication_token(row)
                or ready.child != self._child_token(
                    row, ready.config, self.daemon._admission(str(row["child_admission_id"]))
                )):
            # IO may already have published. The durable applying claim owns
            # exact replay; a stale completion cannot authorize admission.
            del self._publications[operation_id]
            return False
        with phase("preparation_publication_completion_apply", operation_id=operation_id):
            request = PrepareRunRequest.from_dict(_mapping(json.loads(str(row["request_json"]))))
            self._configuration(_mapping(json.loads(str(row["selected_json"]))), request)
            try:
                prepared = pending.future.result()
            except _PublicationChildChanged:
                del self._publications[operation_id]
                return False
            except _PreparationTargetBusy:
                del self._publications[operation_id]
                self._ready_publications[operation_id] = ready
                self._target_retries[operation_id] = monotonic() + 0.1
                return True
            except QueueConflictError:
                del self._publications[operation_id]
                self._fail(row, "publication_conflict", conflict=True)
                return True
            except Exception:
                del self._publications[operation_id]
                raise
            if annotation is not None:
                claim, job = annotation
                del self._annotations[operation_id]
                if claim == ready.claim:
                    # A lost annotation reply leaves the applying claim for exact recovery.
                    del self._publications[operation_id]
                    job.result()
                else:
                    return True
            else:
                job = self.daemon._result_verifications.bulk.submit(
                    operation_id, "preparation_annotation_initialization", self._initialize_owned_context,
                    row, prepared.run_uri, ready.config,
                )
                if job is not None:
                    self._annotations[operation_id] = (ready.claim, job)
                return True
            result = dict(ready.result)
            result["prepared_run"] = prepared.to_dict()
            if ready.publication_owner is not None:
                result["binding"] = {
                    "run_uri": prepared.run_uri,
                    "publication_operation_id": ready.publication_owner,
                }
                result["decision"] = "new_attempt"
            stored = self._store_result(_with_report(
                operation_id, "applying" if row["kind"] == "run" else "applied",
                None, result, ready.report.preflight,
            ), claim=ready.claim)
            if stored and row["kind"] == "run":
                self._continue_run(self._read(operation_id))
            return True

    def _read_report_async(
        self, row: sqlite3.Row, config: LocalDaemonConfig,
        admission: LocalDaemonAdmission, request: PrepareRunRequest,
        binding: PreparationChildInput, token: tuple[object, ...],
    ) -> PreparationReport | None:
        operation_id = str(row["operation_id"])
        assert self.callbacks is not None
        candidate = self._candidates.get(operation_id)
        if candidate is not None and candidate.report_token == token:
            return candidate.report
        pending = self._reports.get(operation_id)
        if pending is not None:
            previous, future = pending
            if not future.done():
                return None
            if previous == token:
                try:
                    return future.result()
                except _PreparationTargetBusy:
                    del self._reports[operation_id]
                    self._target_retries[operation_id] = monotonic() + 0.1
                    return None
                except Exception:
                    del self._reports[operation_id]
                    raise
            del self._reports[operation_id]
        if not self._target_retry_ready(operation_id):
            return None
        if len(self._reports) + len(self._ready_publications) + len(self._publications) >= 2:
            return None
        future = self.daemon._result_verifications.bulk.submit(
            operation_id, "preparation_report_hydration", self.callbacks.read_report,
            config, admission, request, binding,
        )
        if future is not None:
            self._reports[operation_id] = (token, future)
        return None

    def _initialize_owned_context(self, row: sqlite3.Row, run_uri: str, config: LocalDaemonConfig) -> None:
        with self.daemon._publication_guards.hold("preparation-context-" + str(row["operation_id"])):
            self._initialize_context(row, run_uri, config)

    def _initialize_context(self, row: sqlite3.Row, run_uri: str, config: LocalDaemonConfig) -> None:
        from loom.pipeline.stores.local_runs import LocalRunStore

        factory = config.coordinator_authority_factory
        assert factory is not None
        authority = factory(run_uri)
        if authority.read_run_annotations(run_uri) is not None:
            return
        request = PrepareRunRequest.from_dict(_mapping(json.loads(str(row["request_json"]))))
        runtime = LocalRunStore(config.run_store_root).read_runtime_metadata(run_uri) or {}
        context = request.context or SubmissionContext()
        try:
            effective = SubmissionContext(context.description,
                {**cast(Mapping[str, str], runtime.get("tags", {})), **context.tags}, context.metadata)
        except ValueError as exc:
            raise _InvalidInitialContext(str(exc)) from exc
        authority.initialize_run_annotations(run_uri, effective,
            str(row["operation_id"]), self.daemon._require_started())

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
                "SELECT * FROM preparation_operations WHERE kind IN ('run', 'prepare_run') "
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
            if row["kind"] == "prepare_run":
                if row["state"] != "applied":
                    raise QueueConflictError("target preparation and context initialization are incomplete")
                continue
            if row["queue_item_id"] != request.queue_item_id or uri != request.run_uri:
                raise QueueConflictError("reserved run admission identity conflicts")
            if "reconciliation" in selected and operation_id != row["operation_id"]:
                current = self._read(operation_id) if operation_id is not None else None
                if current is not None and current["target_name"] == row["target_name"] and current["principal_id"] == row["principal_id"]:
                    continue
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
        write_status(
            conn, "operation",
            "UPDATE preparation_operations SET state = 'applied', result_code = NULL, result_json = ? WHERE operation_id = ?",
            (_json(projected.result), operation_id),
        )

    def require_admission_claim(self, conn: sqlite3.Connection, operation_id: str,
                                request: LocalDaemonAdmissionRequest, claim: tuple[object, ...], *, child: bool) -> None:
        row = conn.execute("SELECT * FROM preparation_operations WHERE operation_id=?", (operation_id,)).fetchone()
        if (row is None or self._publication_token(row) != claim or row["cancellation_requested"]
                or row["state"] != ("pending" if child else "applying")
                or request.queue_item_id != row["child_name" if child else "queue_item_id"]
                or (child and not row["dispatch_claimed"])):
            raise QueueConflictError("preparation admission claim changed")

    def _submit_async(self, row: sqlite3.Row, request: LocalDaemonAdmissionRequest, *,
                      child: bool = False) -> LocalDaemonAdmission | None:
        operation_id = str(row["operation_id"])
        claim = self._publication_token(row)
        token = (*claim, request, child)
        pending = self._admitting.get(operation_id)
        if pending is not None:
            previous, job = pending
            if not job.done():
                return None
            del self._admitting[operation_id]
            if token == previous:
                return job.result()
        submit = partial(self.daemon._submit, request, preparation_claim=claim,
                         preparation_operation_id=operation_id if child else None,
                         run_operation_id=None if child else operation_id)
        job = self.daemon._result_verifications.bulk.submit(operation_id, "preparation_admission", submit)
        if job is not None:
            self._admitting[operation_id] = token, job
        return None

    def _continue_run(self, row: sqlite3.Row) -> None:
        from .local_daemon import AdmissionNotFoundError, LocalDaemonAdmissionRequest

        operation_id = str(row["operation_id"])
        # Native admission rechecks suppression inside its final transaction.
        row = self._read(operation_id)
        if row["state"] in _TERMINAL:
            return
        claim = self._publication_token(row)
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
            selected = _mapping(json.loads(str(row["selected_json"])))
            reconciliation = selected.get("reconciliation")
            if isinstance(reconciliation, Mapping) and (reconciliation["failed_revision"] is not None or reconciliation.get("cancelled_revision") is not None):
                if row["cancellation_requested"]:
                    self._fail(row, "target_cancelled", conflict=True)
                    return
                try:
                    admission = self._submit_async(row, LocalDaemonAdmissionRequest(
                        str(row["queue_item_id"]), cast(str, prepared["run_uri"]),
                        retry_failed_revision=cast(int | None, reconciliation["failed_revision"]),
                        resume_cancelled_revision=cast(int | None, reconciliation.get("cancelled_revision"))),
                        )
                    if admission is None:
                        return
                except QueueConflictError:
                    self._fail(row, "retry_revision_conflict", conflict=True)
                    return
            def retain(conn):
                current = conn.execute("SELECT * FROM preparation_operations WHERE operation_id=?",
                                       (operation_id,)).fetchone()
                if current["state"] == "applying" and self._publication_token(current) == claim:
                    self.retain_admission(conn, operation_id, admission)
            short_write(self.daemon, retain)
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
            self._submit_async(row, LocalDaemonAdmissionRequest(str(row["queue_item_id"]), cast(str, prepared["run_uri"])))
        except QueueConflictError:
            self._fail(
                self._read(operation_id), "admission_conflict", conflict=True
            )

    def cancel_run(self, operation_id: str, principal_id: str) -> LocalDaemonOperation:
        from .local_daemon import _operation_projection

        cancel_id = _cancel_id(operation_id)

        def cancel(conn, inputs):
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
                return self._projection(old), False
            self.daemon._lifetime.require_accepting()
            if inputs is None:
                return None
            inputs()
            if _operation_projection(conn, cancel_id) is not None:
                raise QueueConflictError("cancellation operation identity is ambiguous")
            result = _mapping(json.loads(str(row["result_json"])))
            superseded = _mapping(json.loads(row["selected_json"])).get("reconciliation", {})
            if isinstance(superseded, Mapping) and superseded.get("superseded_by"):
                original = self._superseded_admission(conn, superseded)
                operation = _operation(cancel_id, "applied", None, {
                    "coordinator_id": result["coordinator_id"], "target_operation_id": operation_id,
                    "queue_item_id": row["queue_item_id"], "admission": original,
                    "native_cancellation_operation_id": original["cancellation_operation_id"],
                    "native_control": {key: original[key] for key in ("admission_id", "state", "revision")},
                })
                write_status(conn, "operation", "INSERT INTO preparation_cancellations VALUES (?, ?, 'applied', NULL, ?)",
                             (cancel_id, operation_id, _json(operation.result)))
                return operation, True
            # Acceptance and demand detachment share one transaction. A restart
            # must not resume a producer using a cancellation that only exists
            # in the public operation table.
            from .local_daemon import _request_admission_cancellation
            native_cancel = None
            bound = "binding" not in result or result["binding"] is not None
            if bound and row["queue_item_id"] is not None and conn.execute("SELECT 1 FROM managed_admissions WHERE queue_item_id = ?", (row["queue_item_id"],)).fetchone() is not None:
                native_cancel = _request_admission_cancellation(conn, str(row["queue_item_id"]), principal_id=principal_id)
            # Suppression retains actual references; it must not require space
            # for an admission which was refused or will never be created.
            cancel_result: dict[str, PlainData] = {
                "coordinator_id": result["coordinator_id"],
                "target_operation_id": operation_id,
                "queue_item_id": result["queue_item_id"],
                "admission": result["admission"],
                "native_cancellation_operation_id": None if native_cancel is None else native_cancel.cancellation_operation_id,
                "native_control": None if native_cancel is None else {
                    "admission_id": native_cancel.admission_id,
                    "state": native_cancel.state.value,
                    "revision": native_cancel.revision,
                },
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
            write_status(
                conn, "operation",
                "UPDATE preparation_operations SET cancellation_requested = 1, result_json = ? WHERE operation_id = ?",
                (_json(projected.result), operation_id),
            )
            selected = _mapping(json.loads(str(row["selected_json"])))
            if bound and "reconciliation" in selected and row["target_name"] is not None:
                write_status(conn, "operation", "UPDATE preparation_operations SET cancellation_requested = 1 WHERE target_name = ? AND principal_id = ?",
                             (row["target_name"], principal_id))
            write_status(
                conn, "operation",
                "INSERT INTO preparation_cancellations VALUES (?, ?, 'pending', NULL, ?)",
                (cancel_id, operation_id, _json(operation.result)),
            )
            return operation, True

        operation, created = self._write_public_operation(
            cancel_id, cancel, conflict="cancellation operation identity is ambiguous",
        )
        if created:
            self.daemon._wake.set()
        return operation

    @staticmethod
    def _superseded_admission(conn, reconciliation):
        receipt = conn.execute("SELECT value FROM daemon_metadata WHERE key = ?",
                               (reconciliation["superseded_by"],)).fetchone()
        return _mapping(json.loads(receipt[0])["cancelled_admission"])

    def _advance_child_release(
        self, operation_id: str,
        transition: Callable[[sqlite3.Connection, str, _ChildReleaseScope | None], _ChildReleaseScope | None],
    ) -> None:
        """Only a completed read with the current membership can settle the control."""
        pending = self._child_release_checks.get(operation_id)
        proof = None
        completed = pending is not None and pending[1].done()
        if pending is not None and completed:
            from ._managed_local import ManagedLocalError
            try:
                if pending[1].result():
                    proof = pending[0]
            except (ManagedLocalError, sqlite3.Error, OSError):
                # The bulk timing records the failed read. Its durable operation
                # stays pending and an unavailable owner is sampled again.
                pass
            if proof is None:
                self._target_retries[operation_id] = monotonic() + 0.1
        try:
            needed = short_write(
                self.daemon, lambda conn: transition(conn, operation_id, proof),
                wait_for_writer=False,
            )
        except sqlite3.OperationalError as exc:
            if (getattr(exc, "sqlite_errorcode", 0) & 255) != sqlite3.SQLITE_BUSY:
                raise
            return
        if pending is not None:
            if needed is not None and not completed:
                return
            # The bulk owner still accounts for a running physical read if
            # the control was superseded while the sample was outstanding.
            del self._child_release_checks[operation_id]
        if needed is None or not self._target_retry_ready(operation_id):
            return
        future = self.daemon._result_verifications.bulk.submit(
            operation_id, "preparation_child_release", needed.coordinator.child_assignments_released,
            tuple(child[1] for child in needed.children),
        )
        if future is not None:
            self._child_release_checks[operation_id] = (needed, future)

    def _child_release_scope(
        self, conn: sqlite3.Connection, target: sqlite3.Row, *, all_children: bool,
    ) -> tuple[bool, _ChildReleaseScope | None]:
        """A claimed dispatch can still be between submission and recording its child ID."""
        if all_children:
            where = "p.target_name = ? AND p.principal_id = ?"
            params = (target["target_name"], target["principal_id"])
        else:
            where = "p.operation_id = ?"
            params = (target["operation_id"],)
        rows = conn.execute(
            "SELECT p.child_admission_id, a.run_uri, a.revision, a.state "
            "FROM preparation_operations p LEFT JOIN managed_admissions a "
            "ON a.admission_id = p.child_admission_id WHERE " + where +
            " AND (p.child_admission_id IS NOT NULL OR "
            "(p.dispatch_claimed = 1 AND p.state IN ('pending','applying'))) "
            "ORDER BY p.child_admission_id", params,
        ).fetchall()
        if not rows:
            return True, None
        execution = self.daemon._execution
        if execution is None or any(row[3] not in _TERMINAL_CHILD_STATES for row in rows):
            return False, None
        return False, _ChildReleaseScope(
            execution.coordinator, target["operation_id"], target["principal_id"], target["target_name"],
            self.daemon._epoch, self.daemon._scheduling_epoch, self.daemon._scheduling_reference_revision,
            tuple((str(row[0]), str(row[1]), int(row[2])) for row in rows),
        )

    def _cancel_child(self, conn, operation_id, proof):
        from .local_daemon import _request_admission_cancellation

        target = conn.execute(
            "SELECT * FROM preparation_operations WHERE operation_id=?", (operation_id,),
        ).fetchone()
        if target["state"] != "pending" or not target["cancellation_requested"] or target["child_admission_id"] is None:
            return None
        _request_admission_cancellation(conn, target["child_name"], principal_id=target["principal_id"])
        _, scope = self._child_release_scope(conn, target, all_children=False)
        if scope is not None and proof == scope:
            write_status(conn, "operation",
                         "UPDATE preparation_operations SET state='cancelled', result_code=NULL WHERE operation_id=?",
                         (operation_id,))
            return None
        return scope

    def _reconcile_cancellations(self, priorities: tuple[tuple[str, ...], ...] = ()) -> None:
        rows, self._cancel_cursor = self._pending_page("cancel", self._cancel_cursor, priorities)
        for row in rows:
            operation_id = str(row["operation_id"])
            with self.daemon._result_verifications.bulk.offering(("cancel", operation_id)):
                self._advance_child_release(operation_id, self._project_cancellation)

    def _project_cancellation(self, conn, operation_id, proof):
        from .local_daemon import _admission_from_row, _request_admission_cancellation

        control = conn.execute(
            "SELECT * FROM preparation_cancellations WHERE operation_id=?", (operation_id,),
        ).fetchone()
        if control["state"] in _TERMINAL:
            return None
        target = conn.execute(
            "SELECT * FROM preparation_operations WHERE operation_id=?", (control["target_operation_id"],),
        ).fetchone()
        target_result = _mapping(json.loads(target["result_json"]))
        result = _mapping(json.loads(control["result_json"]))
        bound = "binding" not in target_result or target_result["binding"] is not None
        reconciliation = _mapping(json.loads(target["selected_json"])).get("reconciliation")
        if bound and target_result["admission"] is None and target["target_name"] is not None and reconciliation is not None:
            row = conn.execute("SELECT * FROM managed_admissions WHERE queue_item_id=?", (target["queue_item_id"],)).fetchone()
            if row is not None:
                target_result["admission"] = _admission_from_row(row).to_dict()
        state = "pending"
        if isinstance(reconciliation, Mapping) and reconciliation.get("superseded_by"):
            original = self._superseded_admission(conn, reconciliation)
            result["admission"] = original
            result["native_cancellation_operation_id"] = original["cancellation_operation_id"]
            result["native_control"] = {key: original[key] for key in ("admission_id", "state", "revision")}
            state = "applied"
            bound = False
        elif target_result["admission"] is not None:
            result["admission"] = target_result["admission"]
            admission = _request_admission_cancellation(conn, target["queue_item_id"], principal_id=target["principal_id"])
            result["native_cancellation_operation_id"] = admission.cancellation_operation_id
            result["native_control"] = {"admission_id": admission.admission_id,
                                        "state": admission.state.value, "revision": admission.revision}
            if admission.state.value in _TERMINAL_CHILD_STATES:
                state = "applied"
        elif target["state"] in _TERMINAL:
            state = "applied"
        needed = None
        if bound and state == "applied" and target["target_name"] is not None:
            empty, scope = self._child_release_scope(conn, target, all_children=True)
            if not empty and (scope is None or scope != proof):
                state, needed = "pending", scope
        if control["state"] != state or json.loads(control["result_json"]) != result:
            projected = _operation(operation_id, state, None, result)
            write_status(conn, "operation",
                         "UPDATE preparation_cancellations SET state=?, result_json=? WHERE operation_id=?",
                         (state, _json(projected.result), operation_id))
        return needed
