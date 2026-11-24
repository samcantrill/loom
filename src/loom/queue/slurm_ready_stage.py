"""Durable SLURM bootstrap contracts and portable terminal diagnostics."""

from __future__ import annotations

from loom._sqlite_policy import SQLitePolicy, connect_existing, initialize_database

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass, replace
import base64
import fcntl
import os
import stat
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
from typing import TYPE_CHECKING, Any, Iterator, Literal, cast

from loom._sqlite_inspection import inspect_sqlite_database
from loom.artifacts import ArtifactRef
from loom.io.uris import uri_to_path
from loom.pipeline.execution.models import (
    STAGE_WORKER_REQUEST_SCHEMA_VERSION,
    ExecutionFailure,
    StageWorkerRequest,
    StageWorkerResult,
)
from loom.pipeline.orchestration import SchedulingProjectionState, StageWorkRecord
from loom.pipeline.planning import StageFingerprintRecord
from loom.pipeline.resources import ResourceRequest
from loom.pipeline.runtime._resource_controls import resource_control_records
from loom.pipeline.runtime.resource_policy import ResourcePolicy
from loom.pipeline.status import StageStatus
from loom.pipeline.stores.atomic import _ensure_durable_parent, atomic_write_bytes
from loom.pipeline.stores.shared_artifacts import binding as shared_binding
from loom.scheduling import SchedulingComponentDescriptor
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.timestamps import parse_timestamp

from ._remote_stage_execution import (
    TRANSFER_CHUNK_BYTES,
    _RemoteArtifact,
    _RemoteExecutionReport,
    _RemoteOutputArtifact,
    _append_exact_chunk,
    _atomic_regular_file,
    _file_digest,
    _published_file_matches,
    _publish_staged_file,
    _read_regular_file_bytes,
    _read_regular_file_range,
    _remote_worker_metadata,
    _validate_remote_interface,
    _validate_remote_semantic_data,
)
from .errors import QueueConflictError, QueueServiceError
from ._slurm_admission import SlurmAdmissionDeferred, validate_gpu_limit

if TYPE_CHECKING:
    from ._agent_process_supervisor import ResidentWorkerLaunchProfile
    from .preparation import PreparationChildInput
    from .submitted_execution import SubmittedContainerExecution

if TYPE_CHECKING:
    from ._agent_process_supervisor import ResidentWorkerLaunchProfile
    from .preparation import PreparationChildInput
    from .submitted_execution import SubmittedContainerExecution

SLURM_STAGE_DELIVERY_SCHEMA_VERSION = 5
_ASSIGNMENT_TABLE = "slurm_stage_assignments"
_OUTPUT_TABLE = "slurm_stage_outputs"


def _reserved_gpu_count(conn: sqlite3.Connection, schema_version: int = 4) -> int:
    return int(conn.execute(
        f"SELECT COALESCE(SUM(requested_gpu_count), 0) FROM {_ASSIGNMENT_TABLE} "
        "WHERE state != 'released'" + (" AND compute_released_at IS NULL" if schema_version >= 5 else "")
    ).fetchone()[0])


@dataclass(frozen=True, slots=True)
class SlurmStageAssignment:
    """One exact submit agent and protected profile bound to a stage attempt."""

    assignment_id: str
    operation_id: str
    run_uri: str
    stage_work_id: str
    stage_name: str
    attempt: int
    attempt_id: str
    profile_id: str
    profile_descriptor: SchedulingComponentDescriptor
    profile_configuration_fingerprint: str
    request_digest: str
    agent_id: str
    agent_root_id: str
    schema_version: int = 2

    def __post_init__(self) -> None:
        if self.schema_version != 2:
            raise QueueServiceError("SLURM assignment schema is unsupported")
        for name in (
            "agent_id",
            "agent_root_id",
            "assignment_id",
            "operation_id",
            "run_uri",
            "stage_work_id",
            "stage_name",
            "attempt_id",
            "profile_id",
            "profile_configuration_fingerprint",
            "request_digest",
        ):
            _text(getattr(self, name), name)
        if (
            isinstance(self.attempt, bool)
            or not isinstance(self.attempt, int)
            or self.attempt < 1
        ):
            raise QueueServiceError("SLURM assignment attempt is invalid")
        if not isinstance(self.profile_descriptor, SchedulingComponentDescriptor):
            raise QueueServiceError("SLURM assignment profile descriptor is invalid")
        if (
            self.profile_descriptor.configuration_fingerprint
            != self.profile_configuration_fingerprint
        ):
            raise QueueConflictError("SLURM assignment profile identity conflicts")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "agent_id": self.agent_id,
            "agent_root_id": self.agent_root_id,
            "assignment_id": self.assignment_id,
            "operation_id": self.operation_id,
            "run_uri": self.run_uri,
            "stage_work_id": self.stage_work_id,
            "stage_name": self.stage_name,
            "attempt": self.attempt,
            "attempt_id": self.attempt_id,
            "profile_id": self.profile_id,
            "profile_descriptor": self.profile_descriptor.to_dict(),
            "profile_configuration_fingerprint": (
                self.profile_configuration_fingerprint
            ),
            "request_digest": self.request_digest,
        }

    @classmethod
    def from_dict(cls, value: object) -> "SlurmStageAssignment":
        mapping = _mapping(value, "SLURM assignment")
        _exact(
            mapping,
            {
                "schema_version",
                "agent_id",
                "agent_root_id",
                "assignment_id",
                "operation_id",
                "run_uri",
                "stage_work_id",
                "stage_name",
                "attempt",
                "attempt_id",
                "profile_id",
                "profile_descriptor",
                "profile_configuration_fingerprint",
                "request_digest",
            },
            "SLURM assignment",
        )
        return cls(
            schema_version=cast(int, mapping["schema_version"]),
            agent_id=cast(str, mapping["agent_id"]),
            agent_root_id=cast(str, mapping["agent_root_id"]),
            assignment_id=cast(str, mapping["assignment_id"]),
            operation_id=cast(str, mapping["operation_id"]),
            run_uri=cast(str, mapping["run_uri"]),
            stage_work_id=cast(str, mapping["stage_work_id"]),
            stage_name=cast(str, mapping["stage_name"]),
            attempt=cast(int, mapping["attempt"]),
            attempt_id=cast(str, mapping["attempt_id"]),
            profile_id=cast(str, mapping["profile_id"]),
            profile_descriptor=SchedulingComponentDescriptor.from_dict(
                mapping["profile_descriptor"]
            ),
            profile_configuration_fingerprint=cast(
                str, mapping["profile_configuration_fingerprint"]
            ),
            request_digest=cast(str, mapping["request_digest"]),
        )


@dataclass(frozen=True, slots=True)
class SlurmStageDelivery:
    """Path-free, execution-only worker request delivered to one bootstrap."""

    assignment_id: str
    stage_work_id: str
    stage_name: str
    attempt: int
    attempt_id: str
    profile_id: str
    project_fingerprint: str
    environment_fingerprint: str
    executor_fingerprint: str
    prepared_at: str
    executor_name: str
    fingerprint: Mapping[str, PlainData]
    resolved_runtime: Mapping[str, PlainData]
    worker_metadata: Mapping[str, PlainData]
    inputs: tuple[_RemoteArtifact, ...]
    declared_outputs: tuple[str, ...]
    schema_version: int = SLURM_STAGE_DELIVERY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SLURM_STAGE_DELIVERY_SCHEMA_VERSION:
            raise QueueServiceError("SLURM delivery schema is unsupported")
        for name in (
            "assignment_id",
            "stage_work_id",
            "stage_name",
            "attempt_id",
            "profile_id",
            "project_fingerprint",
            "environment_fingerprint",
            "executor_fingerprint",
            "prepared_at",
            "executor_name",
        ):
            _identifier(getattr(self, name), name)
        if (
            isinstance(self.attempt, bool)
            or not isinstance(self.attempt, int)
            or self.attempt < 1
        ):
            raise QueueServiceError("SLURM delivery attempt is invalid")
        fingerprint = freeze_plain_data(self.fingerprint, path="SLURM fingerprint")
        runtime = freeze_plain_data(self.resolved_runtime, path="SLURM runtime")
        metadata = freeze_plain_data(self.worker_metadata, path="SLURM metadata")
        if not all(
            isinstance(value, Mapping) for value in (fingerprint, runtime, metadata)
        ):
            raise QueueServiceError("SLURM delivery semantic data is invalid")
        if cast(Mapping[str, PlainData], runtime).get("stage_id") != self.stage_name:
            raise QueueConflictError("SLURM delivery runtime identity conflicts")
        _validate_remote_semantic_data(
            fingerprint=cast(Mapping[str, PlainData], fingerprint),
            resolved_runtime=cast(Mapping[str, PlainData], runtime),
            worker_metadata=cast(Mapping[str, PlainData], metadata),
        )
        fingerprint_record = StageFingerprintRecord.from_dict(fingerprint)
        if fingerprint_record.payload.stage_name != self.stage_name:
            raise QueueConflictError("SLURM stage fingerprint identity conflicts")
        inputs, outputs = _validate_remote_interface(
            fingerprint, metadata, self.inputs, self.declared_outputs,
        )
        from loom.pipeline._project_contracts import EXECUTION, validate_worker_metadata
        from .submitted_execution import assignment_binding
        from .shared_execution import assignment_scope

        submitted = assignment_binding(fingerprint)
        if submitted is not None and assignment_scope(fingerprint) is None:
            raise QueueServiceError("submitted containers require shared execution scope")
        validate_worker_metadata(metadata, node=self.stage_name, attempt=self.attempt, fingerprint=fingerprint_record)
        expected_environment = self.environment_fingerprint if submitted is None else submitted[1].environment_fingerprint
        if EXECUTION in metadata and cast(Mapping[str, PlainData], metadata[EXECUTION])["environment_fingerprint"] != expected_environment:
            raise QueueConflictError("SLURM execution binding environment conflicts")
        object.__setattr__(self, "fingerprint", fingerprint)
        object.__setattr__(self, "resolved_runtime", runtime)
        object.__setattr__(self, "worker_metadata", metadata)
        object.__setattr__(self, "inputs", inputs)
        object.__setattr__(self, "declared_outputs", outputs)
        from ._shared_recovery import validate_wire

        validate_wire(self)

    @classmethod
    def from_worker_request(
        cls,
        *,
        assignment: SlurmStageAssignment,
        worker_request: StageWorkerRequest,
        project_fingerprint: str,
        environment_fingerprint: str,
        executor_fingerprint: str,
        inputs: tuple[_RemoteArtifact, ...],
        declared_outputs: tuple[str, ...],
    ) -> "SlurmStageDelivery":
        if not isinstance(worker_request, StageWorkerRequest):
            raise QueueServiceError("SLURM delivery requires a prepared worker request")
        from loom.pipeline.stores.input_lineage import (
            decode_bindings,
            validate_worker_inputs,
        )

        validate_worker_inputs(
            worker_request,
            decode_bindings(worker_request.metadata.get("attempt_input_bindings")),
        )
        from .submitted_execution import assignment_binding
        submitted = assignment_binding(cast(StageFingerprintRecord, worker_request.fingerprint).to_dict())
        metadata = _remote_worker_metadata(
            worker_request, environment_fingerprint if submitted is None else submitted[1].environment_fingerprint,
        )
        return cls(
            assignment_id=assignment.assignment_id,
            stage_work_id=assignment.stage_work_id,
            stage_name=worker_request.stage_name,
            attempt=worker_request.attempt,
            attempt_id=assignment.attempt_id,
            profile_id=assignment.profile_id,
            project_fingerprint=project_fingerprint,
            environment_fingerprint=environment_fingerprint,
            executor_fingerprint=executor_fingerprint,
            prepared_at=worker_request.prepared_at,
            executor_name=worker_request.executor_name,
            fingerprint=cast(
                StageFingerprintRecord, worker_request.fingerprint
            ).to_dict(),
            resolved_runtime=worker_request.resolved_runtime,
            worker_metadata=metadata,
            inputs=inputs,
            declared_outputs=declared_outputs,
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "assignment_id": self.assignment_id,
            "stage_work_id": self.stage_work_id,
            "stage_name": self.stage_name,
            "attempt": self.attempt,
            "attempt_id": self.attempt_id,
            "profile_id": self.profile_id,
            "project_fingerprint": self.project_fingerprint,
            "environment_fingerprint": self.environment_fingerprint,
            "executor_fingerprint": self.executor_fingerprint,
            "prepared_at": self.prepared_at,
            "executor_name": self.executor_name,
            "fingerprint": thaw_plain_data(self.fingerprint, path="SLURM fingerprint"),
            "resolved_runtime": thaw_plain_data(
                self.resolved_runtime, path="SLURM runtime"
            ),
            "worker_metadata": thaw_plain_data(
                self.worker_metadata, path="SLURM metadata"
            ),
            "inputs": [item.to_dict() for item in self.inputs],
            "declared_outputs": list(self.declared_outputs),
        }

    @classmethod
    def from_dict(cls, value: object) -> "SlurmStageDelivery":
        mapping = _mapping(value, "SLURM delivery")
        if mapping.get("schema_version") != SLURM_STAGE_DELIVERY_SCHEMA_VERSION:
            raise QueueServiceError(
                "SLURM delivery schema is unsupported; finish or cancel the saved "
                "work in its pinned environment and prepare a fresh identity"
            )
        expected = {
            "schema_version",
            "assignment_id",
            "stage_work_id",
            "stage_name",
            "attempt",
            "attempt_id",
            "profile_id",
            "project_fingerprint",
            "environment_fingerprint",
            "executor_fingerprint",
            "prepared_at",
            "executor_name",
            "fingerprint",
            "resolved_runtime",
            "worker_metadata",
            "inputs",
            "declared_outputs",
        }
        _exact(mapping, expected, "SLURM delivery")
        inputs = _sequence(mapping["inputs"], "SLURM delivery inputs")
        outputs = _sequence(mapping["declared_outputs"], "SLURM delivery outputs")
        return cls(
            schema_version=cast(int, mapping["schema_version"]),
            assignment_id=cast(str, mapping["assignment_id"]),
            stage_work_id=cast(str, mapping["stage_work_id"]),
            stage_name=cast(str, mapping["stage_name"]),
            attempt=cast(int, mapping["attempt"]),
            attempt_id=cast(str, mapping["attempt_id"]),
            profile_id=cast(str, mapping["profile_id"]),
            project_fingerprint=cast(str, mapping["project_fingerprint"]),
            environment_fingerprint=cast(str, mapping["environment_fingerprint"]),
            executor_fingerprint=cast(str, mapping["executor_fingerprint"]),
            prepared_at=cast(str, mapping["prepared_at"]),
            executor_name=cast(str, mapping["executor_name"]),
            fingerprint=cast(Mapping[str, PlainData], mapping["fingerprint"]),
            resolved_runtime=cast(Mapping[str, PlainData], mapping["resolved_runtime"]),
            worker_metadata=cast(Mapping[str, PlainData], mapping["worker_metadata"]),
            inputs=tuple(_RemoteArtifact.from_dict(item) for item in inputs),
            declared_outputs=tuple(cast(Sequence[str], outputs)),
        )

    def worker_request(
        self, workspace_root: Path, *, shared_roots: Mapping[str, PlainData] | None = None,
    ) -> StageWorkerRequest:
        root = Path(workspace_root).resolve()
        logs = root / "logs"
        from ._shared_publication import resolve_input

        def input_path(item: _RemoteArtifact) -> Path:
            if shared_binding(item.metadata) is None:
                return root / "inputs" / item.logical_name
            if shared_roots is None:
                raise QueueConflictError("SLURM shared input requires qualified roots")
            return resolve_input(item, shared_roots)

        fingerprint = StageFingerprintRecord.from_dict(self.fingerprint)
        metadata = dict(self.worker_metadata)
        from loom.pipeline._project_contracts import REPORT
        if REPORT in metadata:
            report = next(item for item in self.inputs if item.logical_name == "loom_project_report")
            metadata[REPORT] = report.local_ref(input_path(report)).to_dict()
        return StageWorkerRequest(
            schema_version=STAGE_WORKER_REQUEST_SCHEMA_VERSION,
            run_uri=f"loom-slurm:{self.assignment_id}",
            stage_name=self.stage_name,
            attempt=self.attempt,
            prepared_at=self.prepared_at,
            executor_name=self.executor_name,
            inputs={
                item.logical_name: item.local_ref(input_path(item))
                for item in self.inputs
                if item.logical_name in fingerprint.payload.declared_inputs
            },
            fingerprint=fingerprint,
            stdout_path=str(logs / "stdout.log"),
            stderr_path=str(logs / "stderr.log"),
            traceback_path=str(logs / "traceback.log"),
            result_path=str(root / "worker-result.json"),
            resolved_runtime=self.resolved_runtime,
            metadata=metadata,
        )

    @property
    def preparation_input(self) -> PreparationChildInput | None:
        from ._remote_stage_execution import _preparation_input_from_fingerprint
        return _preparation_input_from_fingerprint(self.fingerprint)

    @property
    def submitted_execution(self) -> SubmittedContainerExecution | None:
        from .submitted_execution import assignment_binding
        binding = assignment_binding(self.fingerprint)
        return None if binding is None else binding[0]


@dataclass(frozen=True, slots=True)
class SlurmStageRecord:
    assignment: SlurmStageAssignment
    delivery: SlurmStageDelivery
    request: Mapping[str, PlainData]
    state: str
    issuer_epoch: str
    job_id: str | None
    cluster: str | None
    bootstrap_incarnation: str | None
    input_ready: bool
    fence: str | None
    process_execution_id: str | None
    report: _RemoteExecutionReport | None
    start_consumed: bool
    agent_evidence_accepted_at: str | None
    requested_gpu_count: int | None = None
    capability_delivery_kind: str | None = None
    capability_expires_at: str | None = None
    publication_requested_at: str | None = None
    publication_completed_at: str | None = None
    publication_cancelled_at: str | None = None
    compute_released_at: str | None = None
    start_request_id: str | None = None
    terminal_observation: Mapping[str, PlainData] | None = None
    agent_sequence: int = 0


@dataclass(frozen=True, slots=True)
class _TaskPageSource:
    assignment_id: str
    mutable_fields: tuple
    submission_json: str | None


_AGENT_PAGE_FILTER = (
    "WHERE a.state != 'released' AND json_extract(a.identity_json, '$.agent_id') = ? "
    "AND json_extract(a.identity_json, '$.agent_root_id') = ? AND a.assignment_id > ? "
    "ORDER BY a.assignment_id LIMIT ?"
)


def ensure_slurm_page_index(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS slurm_active_agent_page ON {_ASSIGNMENT_TABLE}"
        "(json_extract(identity_json, '$.agent_id'), json_extract(identity_json, '$.agent_root_id'), assignment_id) "
        "WHERE state != 'released'"
    )


class SQLiteSlurmStageAssignments:
    """Atomic run/profile reservation and bootstrap/result evidence owner."""

    def __init__(
        self,
        path: str | Path,
        transfer_root: str | Path,
        *,
        _allow_initialize: bool = True,
        sqlite_policy: SQLitePolicy | None = None,
        schema_version: int = 3,
        _on_terminal_operation: Callable[[str], None] | None = None,
    ) -> None:
        if type(schema_version) is not int or schema_version not in {3, 4, 5, 6, 7}:
            raise QueueServiceError("SLURM assignment schema selection is unsupported")
        self.schema_version = schema_version
        self.path = Path(path)
        self.transfer_root = Path(transfer_root)
        self._allow_initialize = _allow_initialize and sqlite_policy is None
        self._sqlite_policy = sqlite_policy
        self._on_terminal_operation = _on_terminal_operation

    def _initialize(self) -> None:
        previous = self._allow_initialize
        self._allow_initialize = True
        try:
            with self._transaction() as conn:
                ensure_slurm_page_index(conn)
        finally:
            self._allow_initialize = previous

    def _open_existing(self) -> None:
        if not self.path.is_file():
            raise QueueServiceError("SLURM assignment store is missing")
        with inspect_sqlite_database(self.path) as conn:
            _require_schema(conn, expected_version=self.schema_version)

    def reserved_gpu_count(self) -> int:
        """Read the durable debit for a scheduling reload under its owner guard."""
        if self.schema_version < 4:
            raise QueueServiceError("SLURM GPU admission requires execution schema 4")
        with self._transaction() as conn:
            return _reserved_gpu_count(conn, self.schema_version)

    def observe_terminal_once(
        self, assignment_id: str, identity: Mapping[str, PlainData], accepted_at: str,
    ) -> Mapping[str, PlainData]:
        """Retain the first exact accounting observation across polls/restarts."""
        if self.schema_version < 7:
            raise QueueServiceError("automatic terminal recovery requires execution schema 7")
        with self._transaction() as conn:
            row = self._row(conn, assignment_id)
            if row["terminal_observation_json"] is not None:
                prior = json.loads(row["terminal_observation_json"])
                if prior["identity"] != identity:
                    raise QueueConflictError("SLURM terminal accounting identity conflicts")
                return prior
            observation = {"identity": dict(identity), "first_observed_at": accepted_at, "probe": None}
            conn.execute(
                f"UPDATE {_ASSIGNMENT_TABLE} SET terminal_observation_json=? WHERE assignment_id=?",
                (_json(observation), assignment_id),
            )
            return observation

    def record_terminal_probe(self, assignment_id: str, probe: Mapping[str, PlainData]) -> None:
        from ._slurm_terminal_recovery import probe_request

        with self._transaction() as conn:
            row = self._row(conn, assignment_id)
            if self.schema_version < 7 or row["terminal_observation_json"] is None:
                raise QueueConflictError("SLURM terminal probe was not requested")
            observation = json.loads(row["terminal_observation_json"])
            if (set(probe) != {"request", "state"}
                or probe["request"] != probe_request(observation)
                or probe["state"] not in {"missing", "available", "unavailable", "invalid"}):
                raise QueueConflictError("SLURM terminal result probe conflicts")
            observation["probe"] = dict(probe)
            conn.execute(
                f"UPDATE {_ASSIGNMENT_TABLE} SET terminal_observation_json=? WHERE assignment_id=?",
                (_json(observation), assignment_id),
            )

    def reserve(
        self,
        assignment: SlurmStageAssignment,
        *,
        request_json: Mapping[str, PlainData],
        delivery: SlurmStageDelivery,
        input_paths: Mapping[str, Path],
        issuer_epoch: str,
        max_parallel_stages: int | None,
        max_profile_outstanding: int | None,
        requested_gpu_count: int | None = None,
        max_reserved_gpus: int | None = None,
        reservation_guard: Callable[[], AbstractContextManager[None]] | None = None,
    ) -> str:
        if not isinstance(assignment, SlurmStageAssignment):
            raise QueueServiceError("SLURM assignment is invalid")
        if delivery.assignment_id != assignment.assignment_id:
            raise QueueConflictError("SLURM delivery assignment conflicts")
        if assignment.request_digest != request_json.get("digest"):
            raise QueueConflictError("SLURM request digest conflicts")
        if self.schema_version >= 4 and (type(requested_gpu_count) is not int or requested_gpu_count < 0):
            raise QueueServiceError("SLURM reservation requires a nonnegative GPU quantity")
        try:
            validate_gpu_limit(max_reserved_gpus)
        except ValueError as exc:
            raise QueueServiceError(str(exc)) from exc
        if max_reserved_gpus is not None and self.schema_version < 4:
            raise QueueServiceError("SLURM GPU admission requires execution schema 4")
        _text(issuer_epoch, "issuer_epoch")
        for value, name in (
            (max_parallel_stages, "run slot limit"),
            (max_profile_outstanding, "profile slot limit"),
        ):
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise QueueServiceError(f"SLURM {name} is invalid")
        paths = {key: Path(value).resolve() for key, value in input_paths.items()}
        expected_transfers = {
            item.transfer_id for item in delivery.inputs
            if shared_binding(item.metadata) is None
        }
        if set(paths) != expected_transfers:
            raise QueueConflictError("SLURM input path set conflicts")
        identity_json = _json(assignment.to_dict())
        request_value = _json(request_json)
        delivery_json = _json(delivery.to_dict())
        input_paths_json = json.dumps(
            {key: str(value) for key, value in sorted(paths.items())},
            sort_keys=True,
            separators=(",", ":"),
        )
        with (reservation_guard() if reservation_guard is not None else nullcontext()), self._transaction() as conn:
            existing = conn.execute(
                f"SELECT * FROM {_ASSIGNMENT_TABLE} WHERE assignment_id = ?",
                (assignment.assignment_id,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["identity_json"]) != identity_json
                    or str(existing["request_json"]) != request_value
                    or str(existing["delivery_json"]) != delivery_json
                    or str(existing["input_paths_json"]) != input_paths_json
                    or self.schema_version >= 4 and existing["requested_gpu_count"] != requested_gpu_count
                ):
                    raise QueueConflictError("SLURM assignment replay conflicts")
                return str(existing["state"])
            row = conn.execute(
                "SELECT record_json FROM stage_work WHERE stage_work_id = ?",
                (assignment.stage_work_id,),
            ).fetchone()
            if row is None:
                raise QueueConflictError("SLURM stage work is missing")
            try:
                work = StageWorkRecord.from_dict(json.loads(str(row[0])))
            except Exception as exc:
                raise QueueConflictError("SLURM stage work is invalid") from exc
            route = work.placement.route
            if self.schema_version >= 4:
                from loom.pipeline.executors.slurm.ready_stage import _ready_stage_requested_gpu_count

                if requested_gpu_count != _ready_stage_requested_gpu_count(work.placement.resource_request):
                    raise QueueConflictError("SLURM GPU quantity conflicts with stage work")
            if (
                work.run_uri != assignment.run_uri
                or work.stage_name != assignment.stage_name
                or work.attempt != assignment.attempt
                or work.attempt_id != assignment.attempt_id
                or work.scheduling_state is not SchedulingProjectionState.READY
                or route.profile_id != assignment.profile_id
                or route.profile_descriptor != assignment.profile_descriptor
                or route.profile_configuration_fingerprint
                != assignment.profile_configuration_fingerprint
            ):
                raise QueueConflictError("SLURM stage work is stale or ineligible")
            managed_work = conn.execute(
                "SELECT 1 FROM coordinator_assignments WHERE stage_work_id = ? "
                "AND state IN ('reserved','bound','accepted','granted','running','unknown')",
                (assignment.stage_work_id,),
            ).fetchone()
            slurm_work = conn.execute(
                f"SELECT 1 FROM {_ASSIGNMENT_TABLE} WHERE stage_work_id = ? "
                "AND state != 'released'",
                (assignment.stage_work_id,),
            ).fetchone()
            if managed_work is not None or slurm_work is not None:
                raise QueueConflictError("stage work already has a live assignment")
            managed_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM coordinator_assignments WHERE run_uri = ? "
                    "AND state IN ('reserved','bound','accepted','granted','running','unknown')",
                    (assignment.run_uri,),
                ).fetchone()[0]
            )
            slurm_count = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM {_ASSIGNMENT_TABLE} WHERE run_uri = ? "
                    "AND state != 'released'",
                    (assignment.run_uri,),
                ).fetchone()[0]
            )
            if max_parallel_stages is not None and managed_count + slurm_count >= max_parallel_stages:
                raise SlurmAdmissionDeferred(
                    "run_active_assignment_limit", "run active-assignment limit reached",
                )
            if max_profile_outstanding is not None:
                profile_count = int(
                    conn.execute(
                        f"SELECT COUNT(*) FROM {_ASSIGNMENT_TABLE} WHERE profile_id = ? "
                        "AND state != 'released'",
                        (assignment.profile_id,),
                    ).fetchone()[0]
                )
                if profile_count >= max_profile_outstanding:
                    raise SlurmAdmissionDeferred(
                        "slurm_profile_outstanding_limit", "SLURM profile outstanding limit reached",
                    )
            if max_reserved_gpus is not None:
                assert requested_gpu_count is not None
                if requested_gpu_count > max_reserved_gpus:
                    raise SlurmAdmissionDeferred(
                        "slurm_gpu_request_exceeds_budget", "SLURM request exceeds GPU reservation budget",
                    )
                if _reserved_gpu_count(conn, self.schema_version) + requested_gpu_count > max_reserved_gpus:
                    raise SlurmAdmissionDeferred(
                        "slurm_gpu_capacity_reserved", "SLURM GPU reservation budget is full",
                    )
            quantity_columns = ", requested_gpu_count" if self.schema_version >= 4 else ""
            quantity_values = ", ?" if self.schema_version >= 4 else ""
            conn.execute(
                f"INSERT INTO {_ASSIGNMENT_TABLE} ("
                "assignment_id, operation_id, run_uri, stage_work_id, profile_id, "
                "state, identity_json, request_json, delivery_json, input_paths_json, "
                "issuer_epoch, job_id, cluster, bootstrap_incarnation, input_ready, "
                "fence, process_execution_id, report_json, capability_verifier, submission_eligible, capability_consumed"
                f"{quantity_columns}) VALUES (?, ?, ?, ?, ?, "
                f"'reserved', ?, ?, ?, ?, ?, NULL, NULL, NULL, 0, NULL, NULL, NULL, NULL, 0, 0{quantity_values})",
                (
                    assignment.assignment_id,
                    assignment.operation_id,
                    assignment.run_uri,
                    assignment.stage_work_id,
                    assignment.profile_id,
                    identity_json,
                    request_value,
                    delivery_json,
                    input_paths_json,
                    issuer_epoch,
                    *((requested_gpu_count,) if self.schema_version >= 4 else ()),
                ),
            )
            decided = StageWorkRecord.from_dict(
                {
                    **work.to_dict(),
                    "scheduling_state": SchedulingProjectionState.DECIDED.value,
                    "scheduling_diagnostics": {
                        "assignment_id": assignment.assignment_id,
                        "target": "slurm",
                        "profile_id": assignment.profile_id,
                    },
                }
            )
            conn.execute(
                "UPDATE stage_work SET scheduling_state = ?, record_json = ? WHERE stage_work_id = ?",
                (decided.scheduling_state.value, _json(decided.to_dict()), assignment.stage_work_id),
            )
        return "reserved"

    def consume_start(self, assignment_id: str, *, request_id: str | None = None) -> bool:
        """Consume once, replaying only the winning live invocation's request.

        Legacy callers keep one-shot semantics. A consumed legacy grant cannot
        be adopted by a new request, including after an explicit schema upgrade.
        """
        if request_id is not None:
            _identifier(request_id, "SLURM start request ID")
            if self.schema_version < 6:
                raise QueueServiceError("replayable SLURM start requires schema 6")
        with self._transaction() as conn:
            row = self._row(conn, assignment_id)
            if row["job_id"] is None or row["fence"] is None:
                raise QueueConflictError("SLURM start requires an exact granted handle")
            if request_id is not None:
                if row["start_consumed"]:
                    return row["start_request_id"] == request_id
                conn.execute(
                    f"UPDATE {_ASSIGNMENT_TABLE} SET start_consumed=1, start_request_id=? WHERE assignment_id=?",
                    (request_id, assignment_id),
                )
                return True
            return (
                conn.execute(
                    f"UPDATE {_ASSIGNMENT_TABLE} SET start_consumed=1 WHERE assignment_id=? AND start_consumed=0",
                    (assignment_id,),
                ).rowcount
                == 1
            )

    def agent_evidence(
        self, assignment_id: str
    ) -> tuple[int, Mapping[str, PlainData] | None]:
        with _connect(self.path, sqlite_policy=self._sqlite_policy, require_existing=True) as conn:
            row = conn.execute(
                f"SELECT agent_sequence, agent_evidence_json FROM {_ASSIGNMENT_TABLE} WHERE assignment_id = ?",
                (assignment_id,),
            ).fetchone()
        if row is None:
            raise QueueConflictError("SLURM assignment is not retained")
        return int(row[0]), None if row[1] is None else json.loads(row[1])

    def accept_agent_evidence(
        self, assignment_id: str, sequence: int, evidence: Mapping[str, PlainData]
    ) -> bool:
        """Accept one ordered agent outbox entry or its exact replay."""
        encoded = _json(evidence)
        with self._transaction() as conn:
            row = self._row(conn, assignment_id)
            current = int(row["agent_sequence"])
            if sequence == current:
                if row["agent_evidence_json"] != encoded:
                    raise QueueConflictError("SLURM agent evidence replay conflicts")
                return False
            if isinstance(sequence, bool) or sequence != current + 1:
                raise QueueConflictError(
                    "SLURM agent evidence sequence is stale or missing"
                )
            conn.execute(
                f"UPDATE {_ASSIGNMENT_TABLE} SET agent_sequence=?, agent_evidence_json=?, agent_evidence_accepted_at=? WHERE assignment_id=?",
                (
                    sequence,
                    encoded,
                    datetime.now(timezone.utc).isoformat(),
                    assignment_id,
                ),
            )
            return True

    def advance(self, assignment_id: str, *, expected: str, next_state: str) -> str:
        allowed = {
            ("reserved", "bound"),
            ("bound", "submitting"),
            ("submitting", "accepted"),
            ("submitting", "unknown"),
            ("submitting", "rejected"),
            ("rejected", "logical_released"),
            ("unknown", "accepted"),
            ("unknown", "conflict"),
            ("accepted", "granted"),
            ("granted", "running"),
            ("granted", "terminal"),
            ("running", "terminal"),
            ("terminal", "logical_released"),
            ("logical_released", "released"),
        }
        if (expected, next_state) not in allowed:
            raise QueueServiceError("invalid SLURM assignment transition")
        with self._transaction(terminal_for=assignment_id if next_state in {"released", "conflict"} else None) as conn:
            row = self._row(conn, assignment_id)
            if str(row["state"]) == next_state:
                return next_state
            if str(row["state"]) != expected:
                raise QueueConflictError("stale SLURM assignment transition")
            conn.execute(
                f"UPDATE {_ASSIGNMENT_TABLE} SET state = ? WHERE assignment_id = ?",
                (next_state, assignment_id),
            )
        return next_state

    def install_capability(
        self,
        assignment_id: str,
        *,
        operation_id: str,
        request_digest: str,
        profile_id: str,
        profile_descriptor: SchedulingComponentDescriptor,
        verifier: str,
        delivery_kind: str | None = None,
        expires_at: str | None = None,
    ) -> None:
        """Durably publish one exact prepared capability to bootstrap authority."""

        if not isinstance(profile_descriptor, SchedulingComponentDescriptor):
            raise QueueServiceError("SLURM capability profile is invalid")
        if delivery_kind is not None:
            if delivery_kind != "user_private_file_v1" or self.schema_version < 4:
                raise QueueServiceError("SLURM capability delivery requires schema 4")
            try:
                if not isinstance(expires_at, str):
                    raise ValueError("missing expiry")
                parse_timestamp(expires_at)
            except ValueError as exc:
                raise QueueServiceError("SLURM capability expiry is invalid") from exc
        elif expires_at is not None:
            raise QueueServiceError("SLURM capability expiry requires a delivery kind")
        if (
            not isinstance(verifier, str)
            or len(verifier) != 64
            or any(char not in "0123456789abcdef" for char in verifier)
        ):
            raise QueueServiceError("SLURM capability verifier is invalid")
        with self._transaction() as conn:
            row = self._row(conn, assignment_id)
            assignment = SlurmStageAssignment.from_dict(
                json.loads(str(row["identity_json"]))
            )
            if (
                assignment.operation_id != operation_id
                or assignment.request_digest != request_digest
                or assignment.profile_id != profile_id
                or assignment.profile_descriptor != profile_descriptor
            ):
                raise QueueConflictError("SLURM capability handoff conflicts")
            retained = cast(str | None, row["capability_verifier"])
            if retained is None:
                if str(row["state"]) != "bound":
                    raise QueueConflictError("SLURM capability handoff is ineligible")
                metadata_sql = ", capability_delivery_kind = ?, capability_expires_at = ?" if self.schema_version >= 4 else ""
                metadata_values = (delivery_kind, expires_at) if self.schema_version >= 4 else ()
                conn.execute(
                    f"UPDATE {_ASSIGNMENT_TABLE} SET capability_verifier = ?{metadata_sql} "
                    "WHERE assignment_id = ?",
                    (verifier, *metadata_values, assignment_id),
                )
            elif (
                not hmac.compare_digest(retained, verifier)
                or self.schema_version >= 4 and (
                    row["capability_delivery_kind"] != delivery_kind
                    or row["capability_expires_at"] != expires_at
                )
            ):
                raise QueueConflictError("SLURM capability handoff conflicts")

    def mark_submission_eligible(
        self,
        assignment_id: str,
        *,
        operation_id: str,
        request_digest: str,
        profile_id: str,
        profile_descriptor: SchedulingComponentDescriptor,
        verifier: str,
        delivery_kind: str | None = None,
        expires_at: str | None = None,
    ) -> None:
        """Mirror the exact pre-run submission barrier to bootstrap authority."""

        self.install_capability(
            assignment_id,
            operation_id=operation_id,
            request_digest=request_digest,
            profile_id=profile_id,
            profile_descriptor=profile_descriptor,
            verifier=verifier,
            delivery_kind=delivery_kind,
            expires_at=expires_at,
        )
        with self._transaction() as conn:
            row = self._row(conn, assignment_id)
            state = str(row["state"])
            if not bool(row["submission_eligible"]):
                if state != "bound":
                    raise QueueConflictError("SLURM submission eligibility conflicts")
                conn.execute(
                    f"UPDATE {_ASSIGNMENT_TABLE} SET state = 'submitting', "
                    "submission_eligible = 1 WHERE assignment_id = ?",
                    (assignment_id,),
                )
            elif state not in {
                "submitting",
                "accepted",
                "granted",
                "running",
                "terminal",
                "logical_released",
                "released",
            }:
                raise QueueConflictError("SLURM submission eligibility conflicts")

    def record_submission(
        self,
        assignment_id: str,
        *,
        state: str,
        job_id: str | None,
        cluster: str | None,
    ) -> str:
        mapped = {
            "intent": "bound",
            "submitting": "submitting",
            "accepted": "accepted",
            "rejected": "rejected",
            "unknown": "unknown",
            "conflict": "conflict",
        }.get(state)
        if mapped is None:
            raise QueueServiceError("SLURM submission state is unsupported")
        with self._transaction(terminal_for=assignment_id) as conn:
            row = self._row(conn, assignment_id)
            current = str(row["state"])
            if current in {
                "granted",
                "running",
                "terminal",
                "logical_released",
                "released",
            }:
                return current
            if current in {"conflict", "rejected"}:
                return current
            if row["job_id"] is not None and (
                str(row["job_id"]) != job_id
                or cast(str | None, row["cluster"]) != cluster
            ):
                conn.execute(
                    f"UPDATE {_ASSIGNMENT_TABLE} SET state = 'conflict' "
                    "WHERE assignment_id = ?",
                    (assignment_id,),
                )
                return "conflict"
            if current == "accepted":
                # Bootstrap handle association can win the race with the
                # acknowledged agent sbatch response. A later weaker outcome must
                # not discard that exact accepted handle.
                if mapped in {"bound", "submitting", "unknown", "rejected"}:
                    return current
                if mapped == "accepted":
                    return current
                if mapped == "conflict":
                    conn.execute(
                        f"UPDATE {_ASSIGNMENT_TABLE} SET state = 'conflict' "
                        "WHERE assignment_id = ?",
                        (assignment_id,),
                    )
                    return "conflict"
            allowed = {
                "reserved": {"bound"},
                "bound": {
                    "bound",
                    "submitting",
                    "accepted",
                    "unknown",
                    "rejected",
                    "conflict",
                },
                "submitting": {
                    "submitting",
                    "accepted",
                    "unknown",
                    "rejected",
                    "conflict",
                },
                "unknown": {"accepted", "unknown", "conflict"},
            }
            if mapped not in allowed.get(current, set()):
                raise QueueConflictError("stale SLURM submission transition")
            conn.execute(
                f"UPDATE {_ASSIGNMENT_TABLE} SET state = ?, job_id = ?, cluster = ? "
                "WHERE assignment_id = ?",
                (mapped, job_id, cluster, assignment_id),
            )
        return mapped

    def register_bootstrap(
        self,
        operation_id: str,
        *,
        request_digest: str,
        job_id: str,
        cluster: str | None,
        incarnation: str,
        capability: str,
        accepted_time: str | None = None,
    ) -> SlurmStageRecord:
        for value, name in (
            (operation_id, "operation_id"),
            (request_digest, "request_digest"),
            (job_id, "job_id"),
            (incarnation, "bootstrap incarnation"),
        ):
            _identifier(value, name)
        if not isinstance(capability, str) or not capability or len(capability) > 8192:
            raise QueueServiceError("job-private capability is invalid")
        with self._transaction() as conn:
            row = conn.execute(
                f"SELECT * FROM {_ASSIGNMENT_TABLE} WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise QueueConflictError("SLURM bootstrap operation is unknown")
            assignment = SlurmStageAssignment.from_dict(
                json.loads(str(row["identity_json"]))
            )
            if assignment.request_digest != request_digest:
                raise QueueConflictError("SLURM bootstrap request digest conflicts")
            verifier = row["capability_verifier"]
            if verifier is None or not bool(row["submission_eligible"]):
                raise QueueConflictError("SLURM bootstrap capability is not prepared")
            if str(row["state"]) not in {"submitting", "accepted"}:
                raise QueueConflictError("SLURM bootstrap submission is ineligible")
            try:
                capability_bytes = base64.b64decode(
                    capability.encode("ascii"), validate=True
                )
            except Exception as exc:
                raise QueueConflictError(
                    "SLURM bootstrap capability is invalid"
                ) from exc
            actual = hashlib.sha256(capability_bytes).hexdigest()
            if not hmac.compare_digest(str(verifier), actual):
                raise QueueConflictError("SLURM bootstrap capability conflicts")
            if row["job_id"] is not None and str(row["job_id"]) != job_id:
                raise QueueConflictError("SLURM bootstrap job handle conflicts")
            existing_cluster = cast(str | None, row["cluster"])
            if existing_cluster is not None and existing_cluster != cluster:
                raise QueueConflictError("SLURM bootstrap cluster conflicts")
            if (
                row["bootstrap_incarnation"] is not None
                and str(row["bootstrap_incarnation"]) != incarnation
            ):
                raise QueueConflictError("SLURM bootstrap incarnation conflicts")
            if bool(row["capability_consumed"]):
                # The same verifier/handle/incarnation is a response-loss replay;
                # all changed bindings above have already failed without mutation.
                return self._record(row)
            if self.schema_version >= 4 and row["capability_delivery_kind"] == "user_private_file_v1":
                if accepted_time is None:
                    raise QueueServiceError("trusted-user first registration requires coordinator accepted time")
                try:
                    expired = parse_timestamp(accepted_time) >= parse_timestamp(row["capability_expires_at"])
                except (TypeError, ValueError) as exc:
                    raise QueueServiceError("SLURM capability time evidence is invalid") from exc
                if expired:
                    raise QueueConflictError("SLURM capability first use has expired")
            conn.execute(
                f"UPDATE {_ASSIGNMENT_TABLE} SET job_id = ?, cluster = ?, "
                "bootstrap_incarnation = ?, capability_consumed = 1 WHERE assignment_id = ?",
                (job_id, cluster, incarnation, assignment.assignment_id),
            )
        return self.read(assignment.assignment_id)

    def mark_input_ready(self, assignment_id: str, incarnation: str) -> bool:
        """Return false until the registered job has the agent's submission acknowledgement."""
        with self._transaction() as conn:
            row = self._row(conn, assignment_id)
            self._incarnation(row, incarnation)
            if str(row["state"]) in {"submitting", "unknown"}:
                return False
            if str(row["state"]) not in {
                "accepted",
                "granted",
                "running",
                "terminal",
                "logical_released",
                "released",
            }:
                raise QueueConflictError("SLURM inputs require an accepted submission")
            conn.execute(
                f"UPDATE {_ASSIGNMENT_TABLE} SET input_ready = 1 WHERE assignment_id = ?",
                (assignment_id,),
            )
        return True

    def mark_granted(self, assignment_id: str, incarnation: str, fence: str) -> str:
        _identifier(fence, "SLURM fence")
        with self._transaction() as conn:
            row = self._row(conn, assignment_id)
            self._incarnation(row, incarnation)
            if not bool(row["input_ready"]):
                raise QueueConflictError("SLURM grant requires durable inputs")
            if row["fence"] is not None and str(row["fence"]) != fence:
                raise QueueConflictError("SLURM grant fence conflicts")
            state = str(row["state"])
            if state not in {
                "accepted",
                "granted",
                "running",
                "terminal",
                "logical_released",
                "released",
            }:
                raise QueueConflictError("SLURM assignment cannot be granted")
            if state == "accepted":
                state = "granted"
            conn.execute(
                f"UPDATE {_ASSIGNMENT_TABLE} SET state = ?, fence = ? "
                "WHERE assignment_id = ?",
                (state, fence, assignment_id),
            )
        return state

    def mark_running(
        self,
        assignment_id: str,
        incarnation: str,
        fence: str,
        process_execution_id: str,
    ) -> None:
        _identifier(process_execution_id, "SLURM process execution ID")
        with self._transaction() as conn:
            row = self._row(conn, assignment_id)
            self._incarnation(row, incarnation)
            if str(row["fence"]) != fence:
                raise QueueConflictError("SLURM running fence conflicts")
            if str(row["state"]) not in {"granted", "running"}:
                raise QueueConflictError("SLURM assignment is not granted")
            if (
                row["process_execution_id"] is not None
                and str(row["process_execution_id"]) != process_execution_id
            ):
                raise QueueConflictError("SLURM process execution identity conflicts")
            conn.execute(
                f"UPDATE {_ASSIGNMENT_TABLE} SET state = 'running', "
                "process_execution_id = ? "
                "WHERE assignment_id = ?",
                (process_execution_id, assignment_id),
            )

    def read(self, assignment_id: str) -> SlurmStageRecord:
        with _connect(self.path, sqlite_policy=self._sqlite_policy, require_existing=True) as conn:
            conn.row_factory = sqlite3.Row
            return self._record(self._row(conn, assignment_id))

    def read_operation(self, operation_id: str) -> SlurmStageRecord:
        with _connect(self.path, sqlite_policy=self._sqlite_policy, require_existing=True) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                f"SELECT * FROM {_ASSIGNMENT_TABLE} WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise QueueConflictError("SLURM operation is not retained")
            return self._record(row)

    def find_operation(self, operation_id: str) -> SlurmStageRecord | None:
        """Return one exact retained operation without weakening store failures."""

        with _connect(self.path, sqlite_policy=self._sqlite_policy, require_existing=True) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                f"SELECT * FROM {_ASSIGNMENT_TABLE} WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            return None if row is None else self._record(row)

    def list_run_unreleased(self, run_uri: str) -> tuple[SlurmStageRecord, ...]:
        with _connect(self.path, sqlite_policy=self._sqlite_policy, require_existing=True) as conn:
            conn.row_factory = sqlite3.Row
            rows = tuple(
                conn.execute(
                    f"SELECT * FROM {_ASSIGNMENT_TABLE} WHERE run_uri = ? "
                    "AND state != 'released' ORDER BY assignment_id",
                    (run_uri,),
                )
            )
            return tuple(self._record(row) for row in rows)

    def recovery_records(
        self, run_uri: str, *, stage_name: str | None = None, limit: int | None = None,
    ) -> tuple[tuple[SlurmStageRecord, Mapping[str, PlainData] | None], ...]:
        """Read bounded attempt history and its accepted provider evidence together."""
        with _connect(self.path, sqlite_policy=self._sqlite_policy, require_existing=True) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT * FROM {_ASSIGNMENT_TABLE} WHERE run_uri = ? "
                "AND (? IS NULL OR json_extract(identity_json, '$.stage_name') = ?) "
                "ORDER BY assignment_id LIMIT ?",
                (run_uri, stage_name, stage_name, -1 if limit is None else limit + 1),
            ).fetchall()
            if limit is not None and len(rows) > limit:
                raise QueueConflictError("recovery history exceeds assignment limit")
            return tuple(
                (self._record(row), None if row["agent_evidence_json"] is None
                 else json.loads(row["agent_evidence_json"]))
                for row in rows
            )

    def list_unreleased(self) -> tuple[SlurmStageRecord, ...]:
        """Return every assignment whose profile binding is still retained."""

        with _connect(self.path, sqlite_policy=self._sqlite_policy, require_existing=True) as conn:
            conn.row_factory = sqlite3.Row
            rows = tuple(
                conn.execute(
                    f"SELECT * FROM {_ASSIGNMENT_TABLE} "
                    "WHERE state != 'released' ORDER BY assignment_id"
                )
            )
            return tuple(self._record(row) for row in rows)

    def pending_storage_page(self, *, after: str | None = None) -> tuple[SlurmStageRecord, ...]:
        """Bound restart discovery to retained publication/release evidence."""
        if self.schema_version < 5:
            return ()
        with self._transaction() as conn:
            rows = conn.execute(
                f"SELECT * FROM {_ASSIGNMENT_TABLE} WHERE state != 'released' AND "
                "((publication_requested_at IS NOT NULL AND publication_completed_at IS NULL AND publication_cancelled_at IS NULL) "
                "OR json_extract(agent_evidence_json, '$.provider_released') = 1) "
                "AND (? IS NULL OR assignment_id > ?) ORDER BY assignment_id LIMIT 32",
                (after, after),
            ).fetchall()
            return tuple(self._record(row) for row in rows)

    def agent_page(
        self, agent_id: str, agent_root_id: str, *, after: str | None = None, limit: int = 33,
    ) -> tuple[SlurmStageRecord, ...]:
        """Bound materialization to one agent's keyset page, including lookahead."""
        if type(limit) is not int or not 1 <= limit <= 33:
            raise QueueServiceError("SLURM task page limit is invalid")
        with _connect(self.path, sqlite_policy=self._sqlite_policy, require_existing=True) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT a.* FROM {_ASSIGNMENT_TABLE} a " + _AGENT_PAGE_FILTER,
                (agent_id, agent_root_id, after or "", limit),
            ).fetchall()
            return tuple(self._record(row) for row in rows)

    def task_page_source(
        self, conn: sqlite3.Connection, agent_id: str, root_id: str, after: str | None,
        *, include_records: bool,
    ) -> tuple[tuple[_TaskPageSource, ...], tuple[SlurmStageRecord, ...]]:
        """Capture mutable task inputs and, on the initial read, the immutable deliveries."""
        columns = [
            "a.assignment_id", "a.state", "a.agent_sequence", "a.job_id", "a.cluster",
            "a.bootstrap_incarnation", "a.process_execution_id", "a.fence", "a.start_consumed",
            "a.report_json IS NOT NULL",
        ]
        if self.schema_version >= 5:
            columns.extend(("a.publication_requested_at", "a.publication_completed_at", "a.compute_released_at"))
        if self.schema_version >= 7:
            columns.append("a.terminal_observation_json")
        columns.append("s.value_json")
        projection = ", ".join(columns)
        if include_records:
            projection += ", a.*"
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT {projection} FROM {_ASSIGNMENT_TABLE} a "
            "LEFT JOIN ready_stage_submissions s ON s.operation_id = a.operation_id "
            + _AGENT_PAGE_FILTER,
            (agent_id, root_id, after or "", 33),
        ).fetchall()
        sources = tuple(_TaskPageSource(row[0], row[1:len(columns) - 1], row[len(columns) - 1]) for row in rows)
        records = tuple(self._record(row) for row in rows[:32]) if include_records else ()
        return sources, records

    def read_input_chunk(
        self, assignment_id: str, incarnation: str, transfer_id: str, offset: int
    ) -> tuple[bytes, bool]:
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise QueueServiceError("SLURM input offset is invalid")
        record = self.read(assignment_id)
        if record.bootstrap_incarnation != incarnation:
            raise QueueConflictError("SLURM bootstrap incarnation conflicts")
        descriptor = next(
            (
                item
                for item in record.delivery.inputs
                if item.transfer_id == transfer_id
            ),
            None,
        )
        if descriptor is None or shared_binding(descriptor.metadata) is not None:
            raise QueueConflictError("SLURM input transfer is not authorized")
        with _connect(self.path, sqlite_policy=self._sqlite_policy, require_existing=True) as conn:
            conn.row_factory = sqlite3.Row
            row = self._row(conn, assignment_id)
            paths = cast(Mapping[str, str], json.loads(str(row["input_paths_json"])))
        path = Path(paths[transfer_id])
        data = _read_regular_file_bytes(path)
        if (
            len(data) != descriptor.size_bytes
            or hashlib.sha256(data).hexdigest() != descriptor.digest
        ):
            raise QueueConflictError("SLURM input bytes changed after reservation")
        if offset > len(data):
            raise QueueConflictError("SLURM input offset exceeds its size")
        chunk = data[offset : offset + TRANSFER_CHUNK_BYTES]
        return chunk, offset + len(chunk) == len(data)

    def request_publication(self, assignment_id: str, incarnation: str, fence: str) -> None:
        """Retain an authenticated shared-report commit request before pending."""
        if self.schema_version < 5:
            raise QueueServiceError("pending publication requires execution schema 5")
        with self._transaction() as conn:
            row = self._row(conn, assignment_id)
            self._incarnation(row, incarnation)
            if row["fence"] != fence or not row["start_consumed"] or row["report_json"] is None:
                raise QueueConflictError("SLURM publication request lacks an exact consumed grant/report")
            report = _RemoteExecutionReport.from_dict(json.loads(row["report_json"]))
            if report.output_kind != "shared":
                raise QueueServiceError("pending publication requires shared output")
            if row["state"] not in {"running", "terminal", "logical_released", "released"}:
                raise QueueConflictError("SLURM publication request state conflicts")
            conn.execute(
                f"UPDATE {_ASSIGNMENT_TABLE} SET publication_requested_at=COALESCE(publication_requested_at, ?) "
                "WHERE assignment_id=?",
                (datetime.now(timezone.utc).isoformat(), assignment_id),
            )

    def cancel_publication(self, assignment_id: str, fence: str) -> None:
        """Persist supersession after exact contained cancellation is committed."""
        if self.schema_version < 5:
            return
        with self._transaction() as conn:
            row = self._row(conn, assignment_id)
            if row["fence"] != fence or row["state"] not in {"logical_released", "released"}:
                raise QueueConflictError("SLURM publication cancellation context conflicts")
            if row["publication_requested_at"] is None or row["publication_completed_at"] is not None:
                return
            conn.execute(
                f"UPDATE {_ASSIGNMENT_TABLE} SET publication_cancelled_at=COALESCE(publication_cancelled_at, ?) "
                "WHERE assignment_id=?", (datetime.now(timezone.utc).isoformat(), assignment_id),
            )

    def complete_publication(self, assignment_id: str, incarnation: str, fence: str) -> None:
        """Record completion after outputs and terminal authority were committed."""
        if self.schema_version < 5:
            return
        with self._transaction() as conn:
            row = self._row(conn, assignment_id)
            self._incarnation(row, incarnation)
            if (row["fence"] != fence or row["report_json"] is None or row["publication_cancelled_at"] is not None
                or row["state"] not in {"terminal", "logical_released", "released"}):
                raise QueueConflictError("SLURM publication completion context conflicts")
            conn.execute(
                f"UPDATE {_ASSIGNMENT_TABLE} SET publication_completed_at=COALESCE(publication_completed_at, ?) "
                "WHERE assignment_id=?", (datetime.now(timezone.utc).isoformat(), assignment_id),
            )

    def declare_report(
        self,
        assignment_id: str,
        incarnation: str,
        fence: str,
        report: _RemoteExecutionReport,
    ) -> None:
        record = self.read(assignment_id)
        if (
            record.bootstrap_incarnation != incarnation
            or record.fence != fence
            or record.state
            not in {"running", "terminal", "logical_released", "released"}
            or report.assignment_id != assignment_id
            or report.stage_name != record.assignment.stage_name
            or report.attempt != record.assignment.attempt
            or report.executor_name != record.delivery.executor_name
        ):
            raise QueueConflictError("SLURM result identity conflicts")
        if report.status is StageStatus.SUCCEEDED and set(
            item.logical_name for item in report.outputs
        ) != set(record.delivery.declared_outputs):
            raise QueueConflictError("SLURM result output interface conflicts")
        from ._preparation_report_transfer import native_role
        from ._shared_publication import selected

        if report.output_kind == "shared" and selected(record.delivery) is None:
            raise QueueConflictError("SLURM shared output was not admitted")

        if report.output_kind == "preparation_report" and not native_role(
            record.delivery.fingerprint
        ):
            raise QueueConflictError(
                "SLURM preparation transfer targets another stage role"
            )
        if (
            report.status is StageStatus.SUCCEEDED
            and native_role(record.delivery.fingerprint)
            and report.output_kind not in {"preparation_report", "shared"}
        ):
            raise QueueConflictError(
                "native preparation transfer capability is missing"
            )
        encoded = _json(report.to_dict())
        with self._transaction() as conn:
            row = self._row(conn, assignment_id)
            self._incarnation(row, incarnation)
            if str(row["fence"]) != fence or str(row["state"]) not in {
                "running",
                "terminal",
                "logical_released",
                "released",
            }:
                raise QueueConflictError("SLURM result authorization changed")
            if row["report_json"] is not None and str(row["report_json"]) != encoded:
                raise QueueConflictError("SLURM result replay conflicts")
            conn.execute(
                f"UPDATE {_ASSIGNMENT_TABLE} SET report_json = ? WHERE assignment_id = ?",
                (encoded, assignment_id),
            )
            for item in report.outputs:
                current = conn.execute(
                    f"SELECT descriptor_json FROM {_OUTPUT_TABLE} "
                    "WHERE assignment_id = ? AND transfer_id = ?",
                    (assignment_id, item.transfer_id),
                ).fetchone()
                descriptor_json = _json(item.to_dict())
                if current is not None and str(current[0]) != descriptor_json:
                    raise QueueConflictError("SLURM output manifest replay conflicts")
                conn.execute(
                    f"INSERT OR IGNORE INTO {_OUTPUT_TABLE} "
                    "(assignment_id, transfer_id, descriptor_json, received_bytes, finalized) "
                    "VALUES (?, ?, ?, 0, 0)",
                    (assignment_id, item.transfer_id, descriptor_json),
                )

    def write_output_chunk(
        self,
        assignment_id: str,
        incarnation: str,
        transfer_id: str,
        offset: int,
        data: bytes,
        *,
        final: bool,
    ) -> int:
        if (
            isinstance(offset, bool)
            or not isinstance(offset, int)
            or offset < 0
            or not isinstance(data, bytes)
            or len(data) > TRANSFER_CHUNK_BYTES
        ):
            raise QueueServiceError("SLURM output chunk is invalid")
        record = self.read(assignment_id)
        if record.bootstrap_incarnation != incarnation:
            raise QueueConflictError("SLURM bootstrap incarnation conflicts")
        # Serialize retries across store instances/processes without holding a
        # SQLite writer through shared-storage IO. Never unlink these locks:
        # waiters must continue to name the same inode after a restart.
        lock_root = self.transfer_root / "transfer-locks"
        lock_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_name = hashlib.sha256((assignment_id + "\0" + transfer_id).encode()).hexdigest()
        fd = os.open(lock_root / lock_name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise QueueConflictError("SLURM output lock is unsafe")
            fcntl.flock(fd, fcntl.LOCK_EX)
            return self._write_locked_output_chunk(
                record, incarnation, transfer_id, offset, data, final=final,
            )
        finally:
            os.close(fd)

    def _write_locked_output_chunk(
        self, record: SlurmStageRecord, incarnation: str, transfer_id: str,
        offset: int, data: bytes, *, final: bool,
    ) -> int:
        assignment_id = record.assignment.assignment_id
        with _connect(self.path, sqlite_policy=self._sqlite_policy, require_existing=True) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                f"SELECT descriptor_json, received_bytes, finalized FROM {_OUTPUT_TABLE} "
                "WHERE assignment_id = ? AND transfer_id = ?",
                (assignment_id, transfer_id),
            ).fetchone()
        if row is None:
            raise QueueConflictError("SLURM output transfer is not declared")
        descriptor = _RemoteOutputArtifact.from_dict(json.loads(str(row[0])))
        if offset + len(data) > descriptor.size_bytes:
            raise QueueConflictError("SLURM output replay exceeds its size")
        target = self.transfer_root / assignment_id / "outputs" / descriptor.logical_name
        part = self.transfer_root / assignment_id / "staging" / f"{transfer_id}.part"
        received = int(row["received_bytes"])
        finalized = bool(row["finalized"])
        if finalized or _published_file_matches(
            target, size_bytes=descriptor.size_bytes, digest=descriptor.digest,
        ):
            if _read_regular_file_range(target, offset, len(data)) != data:
                raise QueueConflictError("SLURM output replay conflicts")
            received, finalized = descriptor.size_bytes, True
        else:
            received = _append_exact_chunk(part, offset, received, data)
            if received > descriptor.size_bytes:
                raise QueueConflictError("SLURM output exceeds its declared size")
            finalized = final or received == descriptor.size_bytes
            if finalized:
                if received != descriptor.size_bytes or _file_digest(part) != descriptor.digest:
                    raise QueueConflictError("SLURM output bytes conflict with manifest")
                _publish_staged_file(part, target)
        if finalized and descriptor.preparation_report_transfer is not None:
            from ._preparation_report_transfer import publish

            publish(descriptor, target)
        # Crash before this commit leaves exact staging/published bytes. Replay
        # verifies those bytes before acknowledging the original chunk.
        with self._transaction() as conn:
            current = self._row(conn, assignment_id)
            if current["bootstrap_incarnation"] != incarnation or current["fence"] != record.fence:
                raise QueueConflictError("SLURM output authorization changed")
            updated = conn.execute(
                f"UPDATE {_OUTPUT_TABLE} SET received_bytes = ?, finalized = ? "
                "WHERE assignment_id = ? AND transfer_id = ? "
                "AND descriptor_json = ? AND received_bytes = ? AND finalized = ?",
                (received, int(finalized), assignment_id, transfer_id,
                 row["descriptor_json"], row["received_bytes"], row["finalized"]),
            )
            if updated.rowcount != 1:
                raise QueueConflictError("SLURM output transfer changed during IO")
        return received

    def committed_result(
        self, assignment_id: str, incarnation: str, fence: str,
        *, shared_outputs: Mapping[str, ArtifactRef] | None = None,
    ) -> tuple[_RemoteExecutionReport, Mapping[str, ArtifactRef]]:
        record = self.read(assignment_id)
        if record.bootstrap_incarnation != incarnation or record.fence != fence:
            raise QueueConflictError("SLURM result authorization conflicts")
        if record.report is None:
            raise QueueConflictError("SLURM result is not declared")
        if record.report.output_kind == "shared":
            if shared_outputs is None or set(shared_outputs) != {
                item.logical_name for item in record.report.outputs
            }:
                raise QueueConflictError("SLURM shared outputs require authoritative publication")
            return record.report, shared_outputs
        with _connect(self.path, sqlite_policy=self._sqlite_policy, require_existing=True) as conn:
            conn.row_factory = sqlite3.Row
            rows = tuple(
                conn.execute(
                    f"SELECT descriptor_json, finalized FROM {_OUTPUT_TABLE} "
                    "WHERE assignment_id = ? ORDER BY transfer_id",
                    (assignment_id,),
                )
            )
        if record.report.status is StageStatus.SUCCEEDED and (
            len(rows) != len(record.report.outputs)
            or any(not bool(row["finalized"]) for row in rows)
        ):
            raise QueueConflictError("SLURM outputs are not coordinator-accessible")
        outputs: dict[str, ArtifactRef] = {}
        for row in rows:
            item = _RemoteOutputArtifact.from_dict(
                json.loads(str(row["descriptor_json"]))
            )
            path = self.transfer_root / assignment_id / "outputs" / item.logical_name
            if not _published_file_matches(
                path, size_bytes=item.size_bytes, digest=item.digest
            ):
                raise QueueConflictError("SLURM committed output bytes are unavailable")
            if item.preparation_report_transfer is not None:
                from ._preparation_report_transfer import publish

                outputs[item.logical_name] = publish(item, path)
                continue
            outputs[item.logical_name] = ArtifactRef(
                artifact_id=item.artifact_id,
                uri=path.resolve().as_uri(),
                artifact_type=item.artifact_type,
                codec_key=item.codec_key,
                schema_version=item.artifact_schema_version,
                checksum=f"sha256:{item.digest}",
                fingerprint=item.fingerprint,
                producer_stage=item.producer_stage,
                created_at=item.created_at,
                metadata=item.metadata,
            )
        return record.report, outputs

    def mark_contained_cancelled(self, assignment_id: str) -> None:
        """Project cancellation only after authority fencing and agent containment."""
        with self._transaction() as conn:
            row = self._row(conn, assignment_id)
            if str(row["state"]) == "released":
                return
            conn.execute(
                f"UPDATE {_ASSIGNMENT_TABLE} SET state='logical_released' WHERE assignment_id=?",
                (assignment_id,),
            )

    def mark_terminal(self, assignment_id: str) -> None:
        record = self.read(assignment_id)
        if record.state in {"logical_released", "released"}:
            return
        if record.state == "terminal":
            self.advance(
                assignment_id,
                expected="terminal",
                next_state="logical_released",
            )
            return
        if record.state not in {"granted", "running"}:
            raise QueueConflictError("SLURM assignment is not result-committable")
        self.advance(assignment_id, expected=record.state, next_state="terminal")
        self.advance(assignment_id, expected="terminal", next_state="logical_released")

    def release_compute(self, assignment_id: str, sequence: int, evidence: Mapping[str, PlainData]) -> None:
        """Debit release after the coordinator validates exact containment/revocation.

        The retained evidence remains the durable owner of unfinished storage;
        this transition neither releases the assignment nor accepts outputs.
        """
        if self.schema_version < 5:
            raise QueueServiceError("independent compute release requires execution schema 5")
        with self._transaction() as conn:
            row = self._row(conn, assignment_id)
            proof = evidence.get("release")
            if (row["agent_sequence"] != sequence or row["agent_evidence_json"] != _json(evidence)
                or evidence.get("provider_released") is not True
                or not isinstance(proof, Mapping)
                or (proof.get("state") != "CONTAINED" and proof != {"kind": "definite_rejection"})
                or (row["state"] not in {"logical_released", "released"}
                    and not (row["publication_requested_at"] is not None and row["report_json"] is not None))):
                raise QueueConflictError("SLURM compute release lacks accepted provider evidence")
            conn.execute(
                f"UPDATE {_ASSIGNMENT_TABLE} SET compute_released_at=COALESCE(compute_released_at, ?) "
                "WHERE assignment_id=?", (datetime.now(timezone.utc).isoformat(), assignment_id),
            )

    def release(self, assignment_id: str) -> None:
        record = self.read(assignment_id)
        if record.state == "released":
            return
        self.advance(assignment_id, expected="logical_released", next_state="released")

    @contextmanager
    def _transaction(self, *, terminal_for: str | None = None) -> Iterator[sqlite3.Connection]:
        if self.path.is_file():
            with inspect_sqlite_database(self.path) as conn:
                initialize = _requires_initialization(conn, self._allow_initialize, self.schema_version)
                if not initialize:
                    _require_schema(conn, expected_version=self.schema_version)
        elif not self._allow_initialize:
            raise QueueServiceError("SLURM assignment store is missing")
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with _connect(self.path, sqlite_policy=self._sqlite_policy, require_existing=not self._allow_initialize) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            if _requires_initialization(conn, self._allow_initialize, self.schema_version):
                effect_columns = (
                    ", publication_requested_at TEXT, publication_completed_at TEXT, publication_cancelled_at TEXT, compute_released_at TEXT"
                    if self.schema_version >= 5 else ""
                )
                if self.schema_version >= 6:
                    effect_columns += ", start_request_id TEXT"
                if self.schema_version >= 7:
                    effect_columns += ", terminal_observation_json TEXT"
                extra_columns = (
                    ", requested_gpu_count INTEGER CHECK ((requested_gpu_count IS NULL AND state = 'released') "
                    "OR (typeof(requested_gpu_count) = 'integer' AND requested_gpu_count >= 0)), "
                    "capability_delivery_kind TEXT, capability_expires_at TEXT, "
                    "CHECK ((capability_delivery_kind IS NULL AND capability_expires_at IS NULL) OR "
                    "(capability_delivery_kind IS NOT NULL AND capability_delivery_kind = 'user_private_file_v1' AND capability_expires_at IS NOT NULL))"
                    if self.schema_version >= 4 else ""
                )
                conn.execute(
                    f"CREATE TABLE {_ASSIGNMENT_TABLE} ("
                    "assignment_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL UNIQUE, "
                    "run_uri TEXT NOT NULL, stage_work_id TEXT NOT NULL, "
                    "profile_id TEXT NOT NULL, state TEXT NOT NULL, "
                    "identity_json TEXT NOT NULL, request_json TEXT NOT NULL, "
                    "delivery_json TEXT NOT NULL, input_paths_json TEXT NOT NULL, "
                    "issuer_epoch TEXT NOT NULL, job_id TEXT, cluster TEXT, "
                    "bootstrap_incarnation TEXT, input_ready INTEGER NOT NULL, "
                    "fence TEXT, process_execution_id TEXT, report_json TEXT, "
                    "capability_verifier TEXT, submission_eligible INTEGER NOT NULL, "
                    "capability_consumed INTEGER NOT NULL, start_consumed INTEGER NOT NULL DEFAULT 0, "
                    f"agent_sequence INTEGER NOT NULL DEFAULT 0, agent_evidence_json TEXT, agent_evidence_accepted_at TEXT{effect_columns}{extra_columns})"
                )
                conn.execute(
                    f"CREATE TABLE {_OUTPUT_TABLE} ("
                    "assignment_id TEXT NOT NULL, transfer_id TEXT NOT NULL, "
                    "descriptor_json TEXT NOT NULL, received_bytes INTEGER NOT NULL, "
                    "finalized INTEGER NOT NULL, "
                    "PRIMARY KEY (assignment_id, transfer_id))"
                )
                _require_schema(conn, allow_unversioned=True, expected_version=self.schema_version)
                conn.execute(f"PRAGMA user_version = {self.schema_version}")
            else:
                _require_schema(conn, expected_version=self.schema_version)
            before = conn.total_changes
            terminal = None
            try:
                yield conn
                if terminal_for is not None and self._on_terminal_operation is not None and conn.total_changes != before:
                    terminal = conn.execute(
                        f"SELECT operation_id FROM {_ASSIGNMENT_TABLE} WHERE assignment_id = ? "
                        "AND state IN ('released', 'conflict')", (terminal_for,),
                    ).fetchone()
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        if terminal is not None and self._on_terminal_operation is not None:
            self._on_terminal_operation(terminal[0])

    @staticmethod
    def _row(conn: sqlite3.Connection, assignment_id: str) -> sqlite3.Row:
        row = conn.execute(
            f"SELECT * FROM {_ASSIGNMENT_TABLE} WHERE assignment_id = ?",
            (assignment_id,),
        ).fetchone()
        if row is None:
            raise QueueConflictError("SLURM assignment is not retained")
        return row

    @staticmethod
    def _incarnation(row: sqlite3.Row, incarnation: str) -> None:
        if (
            row["bootstrap_incarnation"] is None
            or str(row["bootstrap_incarnation"]) != incarnation
        ):
            raise QueueConflictError("SLURM bootstrap incarnation conflicts")

    @staticmethod
    def _record(row: sqlite3.Row) -> SlurmStageRecord:
        report = (
            None
            if row["report_json"] is None
            else _RemoteExecutionReport.from_dict(json.loads(str(row["report_json"])))
        )
        return SlurmStageRecord(
            assignment=SlurmStageAssignment.from_dict(
                json.loads(str(row["identity_json"]))
            ),
            delivery=_retained_delivery(str(row["delivery_json"])),
            request=cast(Mapping[str, PlainData], json.loads(str(row["request_json"]))),
            state=str(row["state"]),
            issuer_epoch=str(row["issuer_epoch"]),
            job_id=cast(str | None, row["job_id"]),
            cluster=cast(str | None, row["cluster"]),
            bootstrap_incarnation=cast(str | None, row["bootstrap_incarnation"]),
            input_ready=bool(row["input_ready"]),
            fence=cast(str | None, row["fence"]),
            process_execution_id=cast(str | None, row["process_execution_id"]),
            report=report,
            start_consumed=bool(row["start_consumed"]),
            start_request_id=(None if "start_request_id" not in row.keys() else row["start_request_id"]),
            terminal_observation=(json.loads(row["terminal_observation_json"]) if "terminal_observation_json" in row.keys() and row["terminal_observation_json"] is not None else None),
            agent_sequence=int(row["agent_sequence"]),
            agent_evidence_accepted_at=cast(
                str | None, row["agent_evidence_accepted_at"]
            ),
            requested_gpu_count=row["requested_gpu_count"] if "requested_gpu_count" in row.keys() else None,
            capability_delivery_kind=row["capability_delivery_kind"] if "capability_delivery_kind" in row.keys() else None,
            capability_expires_at=row["capability_expires_at"] if "capability_expires_at" in row.keys() else None,
            publication_requested_at=row["publication_requested_at"] if "publication_requested_at" in row.keys() else None,
            publication_completed_at=row["publication_completed_at"] if "publication_completed_at" in row.keys() else None,
            publication_cancelled_at=row["publication_cancelled_at"] if "publication_cancelled_at" in row.keys() else None,
            compute_released_at=row["compute_released_at"] if "compute_released_at" in row.keys() else None,
        )


def _decode_retained_delivery(encoded: str) -> SlurmStageDelivery:
    return SlurmStageDelivery.from_dict(json.loads(encoded))


_cached_retained_delivery = lru_cache(maxsize=112)(_decode_retained_delivery)
_cached_large_delivery = lru_cache(maxsize=4)(_decode_retained_delivery)


def _retained_delivery(encoded: str) -> SlurmStageDelivery:
    # Delivery and nested values are immutable. Key by the complete bytes read
    # from SQLite, never by assignment ID or a mutable record revision. Only
    # successful validation is cached; live state and release proofs are not.
    # Bound retained source documents to 32 MiB, excluding decoded-object overhead.
    size = len(encoded.encode("utf-8"))
    if size <= 256 * 1024:
        return _cached_retained_delivery(encoded)
    if size <= 1024 * 1024:
        return _cached_large_delivery(encoded)
    return _decode_retained_delivery(encoded)


class SlurmBootstrapWorkspace:
    """Bootstrap-owned durable inputs and retained output bytes."""

    def __init__(
        self, root: str | Path, assignment_id: str, *,
        durable_files: Literal["best_effort", "strict"] = "best_effort",
    ) -> None:
        _identifier(assignment_id, "assignment_id")
        if durable_files not in {"best_effort", "strict"}:
            raise QueueServiceError("SLURM workspace durable_files is invalid")
        self._durable_files = durable_files
        self.root = Path(root).resolve() / "assignments" / assignment_id
        if durable_files == "strict":
            _ensure_durable_parent(self.root)
        else:
            self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)
        self._delivery_path = self.root / "delivery.json"
        self._registration_path = self.root / "registration.json"
        self._retained_report_path = self.root / "retained-report.json"
        self._execution_binding_path = self.root / "execution-binding.json"

    def persist_execution_binding(
        self, *, agent_id: str, fence: str, profile: ResidentWorkerLaunchProfile,
    ) -> None:
        """Retain the granted attempt's storage identity before executing it."""
        from ._agent_process_supervisor import _profile_value

        _text(agent_id, "SLURM submit agent")
        _text(fence, "SLURM execution fence")
        value = {
            "agent_id": agent_id,
            "execution_fence": fence,
            "profile": _profile_value(profile),
            "delivery_digest": hashlib.sha256(_json(self.delivery().to_dict()).encode()).hexdigest(),
        }
        encoded = (_json(value) + "\n").encode()
        if self._execution_binding_path.exists():
            if self._execution_binding_path.read_bytes() != encoded:
                raise QueueConflictError("SLURM execution binding replay conflicts")
            if self._durable_files != "strict":
                return
        self._write_protocol_file(self._execution_binding_path, encoded)
        self._execution_binding_path.chmod(0o600)

    def publication_binding(self) -> dict[str, Any]:
        if not self._execution_binding_path.is_file():
            raise QueueConflictError("SLURM publication requires a retained execution binding")
        return json.loads(self._execution_binding_path.read_text(encoding="utf-8"))

    def shared_launch_profile(self) -> ResidentWorkerLaunchProfile:
        """Decode the exact authorized image and roots inside the worker namespace."""
        from ._agent_process_supervisor import _profile_from_value
        from .shared_execution import assignment_scope, execution_roots, require_bindings
        from .submitted_execution import assignment_binding

        binding = self.publication_binding()
        request = self.delivery()
        profile = _profile_from_value(binding["profile"])
        submitted = assignment_binding(request.fingerprint)
        if (binding["delivery_digest"] != hashlib.sha256(_json(request.to_dict()).encode()).hexdigest()
            or profile.submitted_execution != request.submitted_execution
            or submitted is not None and dict(profile.descriptor) != submitted[1].to_dict()):
            raise QueueConflictError("SLURM retained launch differs from its delivery")
        scope = assignment_scope(request.fingerprint)
        if scope is not None:
            require_bindings(
                scope, execution_roots(profile.shared_roots, container=profile.container is not None),
                submitted_execution=profile.submitted_execution,
            )
        return profile

    def request(self) -> SlurmStageDelivery:
        """The shared publication protocol's immutable assignment."""
        return self.delivery()

    def persist_delivery(self, delivery: SlurmStageDelivery) -> None:
        if delivery.assignment_id != self.root.name:
            raise QueueConflictError("SLURM delivery targets another workspace")
        encoded = (_json(delivery.to_dict()) + "\n").encode()
        if self._delivery_path.exists():
            if self._delivery_path.read_bytes() != encoded:
                raise QueueConflictError("SLURM delivery replay conflicts")
            if self._durable_files != "strict":
                return
        self._write_protocol_file(self._delivery_path, encoded)
        self._delivery_path.chmod(0o600)

    def persist_registration(self, registration: Mapping[str, PlainData]) -> None:
        """Persist the exact non-secret consume response before file unlink."""
        encoded = (_json(registration) + "\n").encode()
        if self._registration_path.exists():
            if self._registration_path.read_bytes() != encoded:
                raise QueueConflictError("SLURM registration replay conflicts")
            if self._durable_files != "strict":
                return
        self._write_protocol_file(self._registration_path, encoded)
        self._registration_path.chmod(0o600)

    def _write_protocol_file(self, path: Path, data: bytes) -> None:
        if self._durable_files == "strict":
            if path.is_symlink() or path.exists() and not path.is_file():
                raise QueueConflictError("SLURM protocol target is not a regular file")
            atomic_write_bytes(path, data, durability="strict")
        else:
            _atomic_regular_file(path, data)

    def delivery(self) -> SlurmStageDelivery:
        if not self._delivery_path.is_file():
            raise QueueConflictError("SLURM delivery is not durable")
        return SlurmStageDelivery.from_dict(
            json.loads(self._delivery_path.read_text(encoding="utf-8"))
        )

    def stage_input_chunk(
        self, transfer_id: str, offset: int, data: bytes, *, final: bool
    ) -> int:
        delivery = self.delivery()
        item = next(
            (value for value in delivery.inputs if value.transfer_id == transfer_id),
            None,
        )
        if item is None or shared_binding(item.metadata) is not None:
            raise QueueConflictError("SLURM input transfer is not declared")
        if (
            isinstance(offset, bool)
            or not isinstance(offset, int)
            or offset < 0
            or not isinstance(data, bytes)
            or len(data) > TRANSFER_CHUNK_BYTES
        ):
            raise QueueServiceError("SLURM input chunk is invalid")
        target = self.root / "inputs" / item.logical_name
        part = self.root / "input-staging" / f"{transfer_id}.part"
        if _published_file_matches(
            target, size_bytes=item.size_bytes, digest=item.digest
        ):
            existing = _read_regular_file_range(target, offset, len(data))
            if existing != data:
                raise QueueConflictError("SLURM input replay conflicts")
            return item.size_bytes
        received = part.stat().st_size if part.exists() else 0
        received = _append_exact_chunk(part, offset, received, data)
        if received > item.size_bytes:
            raise QueueConflictError("SLURM input exceeds its declared size")
        if final or received == item.size_bytes:
            if received != item.size_bytes or _file_digest(part) != item.digest:
                raise QueueConflictError("SLURM input bytes conflict with delivery")
            _publish_staged_file(part, target)
        return received

    def accept_inputs(self, *, shared_roots: Mapping[str, PlainData] | None = None) -> None:
        for item in self.delivery().inputs:
            if shared_binding(item.metadata) is not None:
                from ._shared_publication import resolve_input
                if shared_roots is None:
                    raise QueueConflictError("SLURM shared input requires qualified roots")
                resolve_input(item, shared_roots)
                continue
            path = self.root / "inputs" / item.logical_name
            if not _published_file_matches(
                path, size_bytes=item.size_bytes, digest=item.digest
            ):
                raise QueueConflictError("SLURM inputs are not durable")

    def worker_request(self, *, shared_roots: Mapping[str, PlainData] | None = None) -> StageWorkerRequest:
        self.accept_inputs(shared_roots=shared_roots)
        request = self.delivery().worker_request(self.root, shared_roots=shared_roots)
        from ._shared_recovery import WIRE, worker_bindings
        from ._shared_staging_continuation import WIRE as staging_wire

        metadata = dict(request.metadata)
        metadata.pop(WIRE, None)
        metadata.pop(staging_wire, None)
        metadata.update(worker_bindings(self))
        return replace(request, metadata=metadata)

    def retain_result(self, result: StageWorkerResult) -> _RemoteExecutionReport:
        """Retain a result produced inside the acknowledged bootstrap root.

        The accepted ready-stage script allocates the full normalized demand
        through SBATCH. This reports delegation, not measured isolation or an
        additional native-process limit. Replay uses the retained report without
        launching a new root or upgrading legacy evidence.
        """

        delivery = self.delivery()
        if (
            result.run_uri != f"loom-slurm:{delivery.assignment_id}"
            or result.stage_name != delivery.stage_name
            or result.attempt != delivery.attempt
        ):
            raise QueueConflictError("SLURM worker result identity conflicts")
        outputs: list[_RemoteOutputArtifact] = []
        from ._shared_publication import selected, retain
        shared = selected(delivery) is not None
        if result.status is StageStatus.SUCCEEDED:
            if set(result.outputs) != set(delivery.declared_outputs):
                raise QueueConflictError("SLURM worker outputs conflict")
            if shared:
                outputs = retain(self, result)
            for logical_name, ref in (() if shared else sorted(result.outputs.items())):
                unresolved_source = uri_to_path(ref.uri)
                if unresolved_source.is_symlink():
                    raise QueueConflictError("SLURM preparation output is a link")
                source = unresolved_source.resolve(strict=True)
                source.relative_to(self.root)
                data = _read_regular_file_bytes(source)
                from ._preparation_report_transfer import frame, native_role

                transfer = None
                if native_role(delivery.fingerprint):
                    if logical_name != "report":
                        raise QueueConflictError(
                            "SLURM preparation output role conflicts"
                        )
                    data, transfer = frame(ref, source)
                digest = hashlib.sha256(data).hexdigest()
                if (
                    transfer is None
                    and ref.checksum is not None
                    and ref.checksum != f"sha256:{digest}"
                ):
                    raise QueueConflictError("SLURM output checksum conflicts")
                transfer_id = (
                    "output-"
                    + hashlib.sha256(
                        (
                            delivery.assignment_id + "\0" + logical_name + "\0" + digest
                        ).encode()
                    ).hexdigest()
                )
                target = self.root / "retained-outputs" / logical_name
                _atomic_regular_file(target, data)
                outputs.append(
                    _RemoteOutputArtifact(
                        transfer_id=transfer_id,
                        logical_name=logical_name,
                        digest=digest,
                        size_bytes=len(data),
                        artifact_id=ref.artifact_id,
                        artifact_type=ref.artifact_type,
                        codec_key=ref.codec_key,
                        artifact_schema_version=ref.schema_version,
                        fingerprint=ref.fingerprint,
                        producer_stage=ref.producer_stage,
                        created_at=ref.created_at,
                        metadata=ref.metadata,
                        preparation_report_transfer=transfer,
                    )
                )
        failure = cast(ExecutionFailure | None, result.failure)
        entries = ResourceRequest.from_dict(
            delivery.resolved_runtime["resources"]
        ).entries
        allocation_policy = ResourcePolicy(enforce="all")
        controls = resource_control_records(
            entries=entries,
            policy=allocation_policy,
            selection=allocation_policy.select(entries),
            owner="slurm",
            mechanisms={kind: "sbatch_allocation" for kind in entries},
            selected_disposition="delegated",
        )
        report = _RemoteExecutionReport(
            assignment_id=delivery.assignment_id,
            stage_name=delivery.stage_name,
            attempt=delivery.attempt,
            status=result.status,
            started_at=result.started_at,
            finished_at=result.finished_at,
            executor_name=result.executor_name,
            outputs=tuple(outputs),
            failure_type=None if failure is None else failure.failure_type,
            message=None if failure is None else failure.message,
            exception_type=None if failure is None else failure.exception_type,
            exit_code=result.exit_code,
            failure=failure,
            resource_controls=cast(
                tuple[Mapping[str, PlainData], ...], tuple(controls)
            ),
            process_created=True,
            executor_metadata=result.executor_metadata,
            output_kind="shared" if shared else "preparation_report"
            if any(item.preparation_report_transfer is not None for item in outputs)
            else "relay",
        )
        encoded = (_json(report.to_dict()) + "\n").encode()
        if self._retained_report_path.exists():
            if self._retained_report_path.read_bytes() != encoded:
                raise QueueConflictError("SLURM retained result replay conflicts")
        else:
            _atomic_regular_file(self._retained_report_path, encoded)
            self._retained_report_path.chmod(0o600)
        return report

    def retained_report(self) -> _RemoteExecutionReport | None:
        """Return a locally retained result for replay without another root launch."""

        if not self._retained_report_path.is_file():
            return None
        try:
            value = json.loads(self._retained_report_path.read_text(encoding="utf-8"))
            return _RemoteExecutionReport.from_dict(value)
        except Exception as exc:
            raise QueueConflictError("SLURM retained result is invalid") from exc

    def output_chunk(self, transfer_id: str, offset: int) -> tuple[bytes, bool]:
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise QueueServiceError("SLURM output offset is invalid")
        path = self.root / "retained-outputs"
        matches = (
            tuple(item for item in path.iterdir() if item.is_file())
            if path.is_dir()
            else ()
        )
        for item in matches:
            data = _read_regular_file_bytes(item)
            digest = hashlib.sha256(data).hexdigest()
            expected = (
                "output-"
                + hashlib.sha256(
                    (self.root.name + "\0" + item.name + "\0" + digest).encode()
                ).hexdigest()
            )
            if expected == transfer_id:
                if offset > len(data):
                    raise QueueConflictError("SLURM output offset exceeds its size")
                chunk = data[offset : offset + TRANSFER_CHUNK_BYTES]
                return chunk, offset + len(chunk) == len(data)
        raise QueueConflictError("SLURM output transfer is unavailable")


def _connect(path: Path, *, require_existing: bool = False, sqlite_policy: SQLitePolicy | None = None) -> sqlite3.Connection:
    if sqlite_policy is not None:
        connect = connect_existing if require_existing else initialize_database
        return connect(path, policy=sqlite_policy, isolation_level="")
    target: str | Path = (
        f"{path.resolve().as_uri()}?mode=rw" if require_existing else path
    )
    return sqlite3.connect(target, uri=require_existing)


def _requires_initialization(conn: sqlite3.Connection, allowed: bool, expected_version: int = 3) -> bool:
    # Fresh coordinator setup creates its shared database before this owner.
    # Any retained assignment/output table must pass full current admission.
    if not allowed:
        return False
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN (?, ?)",
        (_ASSIGNMENT_TABLE, _OUTPUT_TABLE),
    ).fetchall()
    if tables:
        return False
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version not in {0, expected_version}:
        raise QueueServiceError("SLURM assignment store schema is unsupported")
    return True


def _upgrade_released_schema(conn: sqlite3.Connection) -> None:
    """Convert a stopped, snapshotted v3 assignment/projection database to v4.

    The explicit upgrade owner supplies the transaction and verifies the other
    owners of this shared database. No ordinary open calls this function.
    Released history keeps unknown quantities and legacy credential semantics.
    """
    _require_schema(conn, expected_version=3)
    if not conn.in_transaction:
        raise QueueServiceError("SLURM schema conversion requires an upgrade transaction")
    if conn.execute(f"SELECT 1 FROM {_ASSIGNMENT_TABLE} WHERE state != 'released' LIMIT 1").fetchone():
        raise QueueServiceError("SLURM schema conversion requires released assignments")
    conn.execute(
        f"ALTER TABLE {_ASSIGNMENT_TABLE} ADD COLUMN requested_gpu_count INTEGER "
        "CHECK ((requested_gpu_count IS NULL AND state = 'released') OR "
        "(typeof(requested_gpu_count) = 'integer' AND requested_gpu_count >= 0))"
    )
    conn.execute(f"ALTER TABLE {_ASSIGNMENT_TABLE} ADD COLUMN capability_delivery_kind TEXT")
    conn.execute(
        f"ALTER TABLE {_ASSIGNMENT_TABLE} ADD COLUMN capability_expires_at TEXT "
        "CHECK ((capability_delivery_kind IS NULL AND capability_expires_at IS NULL) OR "
        "(capability_delivery_kind IS NOT NULL AND capability_delivery_kind = 'user_private_file_v1' "
        "AND capability_expires_at IS NOT NULL))"
    )
    conn.execute("PRAGMA user_version = 4")
    _require_schema(conn, expected_version=4)


def _upgrade_pending_effects_schema(conn: sqlite3.Connection) -> None:
    """Upgrade a stopped v4 owner inside the supported upgrade transaction.

    Existing assignments retain their GPU debit and acquire no publication
    intent. Later reconciliation must validate evidence before either changes.
    """
    _require_schema(conn, expected_version=4)
    if not conn.in_transaction:
        raise QueueServiceError("SLURM schema conversion requires an upgrade transaction")
    conn.execute(f"ALTER TABLE {_ASSIGNMENT_TABLE} ADD COLUMN publication_requested_at TEXT")
    conn.execute(f"ALTER TABLE {_ASSIGNMENT_TABLE} ADD COLUMN publication_completed_at TEXT")
    conn.execute(f"ALTER TABLE {_ASSIGNMENT_TABLE} ADD COLUMN publication_cancelled_at TEXT")
    conn.execute(f"ALTER TABLE {_ASSIGNMENT_TABLE} ADD COLUMN compute_released_at TEXT")
    conn.execute("PRAGMA user_version = 5")
    _require_schema(conn, expected_version=5)


def _upgrade_start_request_schema(conn: sqlite3.Connection) -> None:
    """Retain old consumed grants as legacy; never invent a request owner."""
    _require_schema(conn, expected_version=5)
    if not conn.in_transaction:
        raise QueueServiceError("SLURM schema conversion requires an upgrade transaction")
    conn.execute(f"ALTER TABLE {_ASSIGNMENT_TABLE} ADD COLUMN start_request_id TEXT")
    conn.execute("PRAGMA user_version = 6")
    _require_schema(conn, expected_version=6)


def _upgrade_terminal_observation_schema(conn: sqlite3.Connection) -> None:
    """Old assignments begin a grace period only after a new exact observation."""
    _require_schema(conn, expected_version=6)
    if not conn.in_transaction:
        raise QueueServiceError("SLURM schema conversion requires an upgrade transaction")
    conn.execute(f"ALTER TABLE {_ASSIGNMENT_TABLE} ADD COLUMN terminal_observation_json TEXT")
    conn.execute("PRAGMA user_version = 7")
    _require_schema(conn, expected_version=7)


def _require_schema(
    conn: sqlite3.Connection, *, allow_unversioned: bool = False, expected_version: int = 3,
) -> None:
    expected = {
        "assignment_id",
        "operation_id",
        "run_uri",
        "stage_work_id",
        "profile_id",
        "state",
        "identity_json",
        "request_json",
        "delivery_json",
        "input_paths_json",
        "issuer_epoch",
        "job_id",
        "cluster",
        "bootstrap_incarnation",
        "input_ready",
        "fence",
        "process_execution_id",
        "report_json",
        "capability_verifier",
        "submission_eligible",
        "capability_consumed",
        "start_consumed",
        "agent_sequence",
        "agent_evidence_json",
        "agent_evidence_accepted_at",
    }
    if expected_version >= 4:
        expected |= {"requested_gpu_count", "capability_delivery_kind", "capability_expires_at"}
    if expected_version >= 5:
        expected |= {"publication_requested_at", "publication_completed_at", "publication_cancelled_at", "compute_released_at"}
    if expected_version >= 6:
        expected.add("start_request_id")
    if expected_version >= 7:
        expected.add("terminal_observation_json")
    columns = {
        str(row[1]) for row in conn.execute(f"PRAGMA table_info({_ASSIGNMENT_TABLE})")
    }
    output_columns = {
        str(row[1]) for row in conn.execute(f"PRAGMA table_info({_OUTPUT_TABLE})")
    }
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if (
        (version != expected_version and not (allow_unversioned and version == 0))
        or columns != expected
        or output_columns
        != {
            "assignment_id",
            "transfer_id",
            "descriptor_json",
            "received_bytes",
            "finalized",
        }
    ):
        raise QueueServiceError("SLURM assignment store schema is unsupported")
    if expected_version >= 4 and conn.execute(
        f"SELECT 1 FROM {_ASSIGNMENT_TABLE} WHERE "
        "(state != 'released' AND requested_gpu_count IS NULL) OR requested_gpu_count < 0 "
        "OR (requested_gpu_count IS NOT NULL AND typeof(requested_gpu_count) != 'integer') "
        "OR (capability_delivery_kind IS NULL AND capability_expires_at IS NOT NULL) "
        "OR (capability_delivery_kind IS NOT NULL AND (capability_delivery_kind != 'user_private_file_v1' "
        "OR capability_expires_at IS NULL)) LIMIT 1"
    ).fetchone():
        raise QueueServiceError("SLURM assignment store has invalid quantity or credential evidence")


def _json(value: Mapping[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise QueueServiceError(f"{path} must be a string-keyed mapping")
    return cast(Mapping[str, object], value)


def _sequence(value: object, path: str) -> tuple[object, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise QueueServiceError(f"{path} must be a sequence")
    return tuple(value)


def _exact(value: Mapping[str, object], expected: set[str], path: str) -> None:
    if set(value) != expected:
        raise QueueServiceError(f"{path} fields are unsupported")


def _text(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 1024
        or any(ord(char) < 32 for char in value)
    ):
        raise QueueServiceError(f"{field} is invalid")
    return value


def _identifier(value: object, field: str) -> str:
    text = _text(value, field)
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:@+"
    if len(text) > 160 or any(char not in allowed for char in text):
        raise QueueServiceError(f"{field} is invalid")
    return text


__all__ = [
    "SLURM_STAGE_DELIVERY_SCHEMA_VERSION",
    "SQLiteSlurmStageAssignments",
    "SlurmBootstrapWorkspace",
    "SlurmStageAssignment",
    "SlurmStageDelivery",
    "SlurmStageRecord",
]
