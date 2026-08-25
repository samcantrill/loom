"""Durable coordinator and path-free bootstrap contracts for ready-stage SLURM."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import base64
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
from typing import Iterator, cast

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
from loom.pipeline.status import StageStatus
from loom.scheduling import SchedulingComponentDescriptor
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data

from ._remote_stage_execution import (
    MAX_TRANSFER_BYTES,
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
    _validate_remote_semantic_data,
)
from .errors import QueueConflictError, QueueServiceError


SLURM_STAGE_DELIVERY_SCHEMA_VERSION = 3
_ASSIGNMENT_TABLE = "slurm_stage_assignments"
_OUTPUT_TABLE = "slurm_stage_outputs"


@dataclass(frozen=True, slots=True)
class SlurmStageAssignment:
    """The closed SLURM target; it deliberately has no agent or claim identity."""

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

    def __post_init__(self) -> None:
        for name in (
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
        inputs = tuple(self.inputs)
        outputs = tuple(
            _identifier(item, "declared output") for item in self.declared_outputs
        )
        if (
            any(not isinstance(item, _RemoteArtifact) for item in inputs)
            or len(inputs) > 32
            or len({item.logical_name for item in inputs}) != len(inputs)
            or sum(item.size_bytes for item in inputs) > MAX_TRANSFER_BYTES
        ):
            raise QueueServiceError("SLURM delivery inputs are invalid")
        if len(outputs) > 32 or len(set(outputs)) != len(outputs):
            raise QueueServiceError("SLURM delivery outputs are invalid")
        if set(item.logical_name for item in inputs) != set(
            fingerprint_record.payload.declared_inputs
        ) or set(outputs) != set(fingerprint_record.payload.declared_outputs):
            raise QueueConflictError("SLURM delivery interface conflicts")
        object.__setattr__(self, "fingerprint", fingerprint)
        object.__setattr__(self, "resolved_runtime", runtime)
        object.__setattr__(self, "worker_metadata", metadata)
        object.__setattr__(self, "inputs", inputs)
        object.__setattr__(self, "declared_outputs", outputs)

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
        metadata: dict[str, PlainData] = {}
        if "stage_resources" in worker_request.metadata:
            metadata["stage_resources"] = worker_request.metadata["stage_resources"]
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

    def worker_request(self, workspace_root: Path) -> StageWorkerRequest:
        root = Path(workspace_root).resolve()
        logs = root / "logs"
        return StageWorkerRequest(
            schema_version=STAGE_WORKER_REQUEST_SCHEMA_VERSION,
            run_uri=f"loom-slurm:{self.assignment_id}",
            stage_name=self.stage_name,
            attempt=self.attempt,
            prepared_at=self.prepared_at,
            executor_name=self.executor_name,
            inputs={
                item.logical_name: item.local_ref(root / "inputs" / item.logical_name)
                for item in self.inputs
            },
            fingerprint=StageFingerprintRecord.from_dict(self.fingerprint),
            stdout_path=str(logs / "stdout.log"),
            stderr_path=str(logs / "stderr.log"),
            traceback_path=str(logs / "traceback.log"),
            result_path=str(root / "worker-result.json"),
            resolved_runtime=self.resolved_runtime,
            metadata=self.worker_metadata,
        )


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


class SQLiteSlurmStageAssignments:
    """Atomic run/profile reservation and bootstrap/result evidence owner."""

    def __init__(
        self,
        path: str | Path,
        transfer_root: str | Path,
        *,
        _allow_initialize: bool = True,
    ) -> None:
        self.path = Path(path)
        self.transfer_root = Path(transfer_root)
        self._allow_initialize = _allow_initialize

    def _initialize(self) -> None:
        with self._transaction():
            pass

    def _open_existing(self) -> None:
        if not self.path.is_file():
            raise QueueServiceError("SLURM assignment store is missing")
        with _connect(self.path, require_existing=True) as conn:
            conn.row_factory = sqlite3.Row
            _require_schema(conn)

    def reserve(
        self,
        assignment: SlurmStageAssignment,
        *,
        request_json: Mapping[str, PlainData],
        delivery: SlurmStageDelivery,
        input_paths: Mapping[str, Path],
        issuer_epoch: str,
        max_parallel_stages: int,
        max_profile_outstanding: int,
    ) -> str:
        if not isinstance(assignment, SlurmStageAssignment):
            raise QueueServiceError("SLURM assignment is invalid")
        if delivery.assignment_id != assignment.assignment_id:
            raise QueueConflictError("SLURM delivery assignment conflicts")
        if assignment.request_digest != request_json.get("digest"):
            raise QueueConflictError("SLURM request digest conflicts")
        _text(issuer_epoch, "issuer_epoch")
        for value, name in (
            (max_parallel_stages, "run slot limit"),
            (max_profile_outstanding, "profile slot limit"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise QueueServiceError(f"SLURM {name} is invalid")
        paths = {key: Path(value).resolve() for key, value in input_paths.items()}
        expected_transfers = {item.transfer_id for item in delivery.inputs}
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
        with self._transaction() as conn:
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
                    or str(existing["issuer_epoch"]) != issuer_epoch
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
                "AND state NOT IN ('rejected','released')",
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
                    "AND state NOT IN ('rejected','released')",
                    (assignment.run_uri,),
                ).fetchone()[0]
            )
            if managed_count + slurm_count >= max_parallel_stages:
                raise QueueServiceError("run active-assignment limit reached")
            profile_count = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM {_ASSIGNMENT_TABLE} WHERE profile_id = ? "
                    "AND state NOT IN ('rejected','released')",
                    (assignment.profile_id,),
                ).fetchone()[0]
            )
            if profile_count >= max_profile_outstanding:
                raise QueueServiceError("SLURM profile outstanding limit reached")
            conn.execute(
                f"INSERT INTO {_ASSIGNMENT_TABLE} ("
                "assignment_id, operation_id, run_uri, stage_work_id, profile_id, "
                "state, identity_json, request_json, delivery_json, input_paths_json, "
                "issuer_epoch, job_id, cluster, bootstrap_incarnation, input_ready, "
                "fence, process_execution_id, report_json, capability_verifier, submission_eligible, capability_consumed) VALUES (?, ?, ?, ?, ?, "
                "'reserved', ?, ?, ?, ?, ?, NULL, NULL, NULL, 0, NULL, NULL, NULL, NULL, 0, 0)",
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
                "UPDATE stage_work SET record_json = ? WHERE stage_work_id = ?",
                (_json(decided.to_dict()), assignment.stage_work_id),
            )
        return "reserved"

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
        with self._transaction() as conn:
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
    ) -> None:
        """Durably publish one exact prepared capability to bootstrap authority."""

        if not isinstance(profile_descriptor, SchedulingComponentDescriptor):
            raise QueueServiceError("SLURM capability profile is invalid")
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
                conn.execute(
                    f"UPDATE {_ASSIGNMENT_TABLE} SET capability_verifier = ? "
                    "WHERE assignment_id = ?",
                    (verifier, assignment_id),
                )
            elif not hmac.compare_digest(retained, verifier):
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
    ) -> None:
        """Mirror the exact pre-run submission barrier to bootstrap authority."""

        self.install_capability(
            assignment_id,
            operation_id=operation_id,
            request_digest=request_digest,
            profile_id=profile_id,
            profile_descriptor=profile_descriptor,
            verifier=verifier,
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
        with self._transaction() as conn:
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
                # coordinator-side sbatch response. A later weaker outcome must
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
            conn.execute(
                f"UPDATE {_ASSIGNMENT_TABLE} SET job_id = ?, cluster = ?, "
                "bootstrap_incarnation = ?, capability_consumed = 1 WHERE assignment_id = ?",
                (job_id, cluster, incarnation, assignment.assignment_id),
            )
        return self.read(assignment.assignment_id)

    def mark_input_ready(self, assignment_id: str, incarnation: str) -> None:
        with self._transaction() as conn:
            row = self._row(conn, assignment_id)
            self._incarnation(row, incarnation)
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
        with _connect(self.path, require_existing=True) as conn:
            conn.row_factory = sqlite3.Row
            return self._record(self._row(conn, assignment_id))

    def read_operation(self, operation_id: str) -> SlurmStageRecord:
        with _connect(self.path, require_existing=True) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                f"SELECT * FROM {_ASSIGNMENT_TABLE} WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise QueueConflictError("SLURM operation is not retained")
            return self._record(row)

    def list_run_unreleased(self, run_uri: str) -> tuple[SlurmStageRecord, ...]:
        with _connect(self.path, require_existing=True) as conn:
            conn.row_factory = sqlite3.Row
            rows = tuple(
                conn.execute(
                    f"SELECT * FROM {_ASSIGNMENT_TABLE} WHERE run_uri = ? "
                    "AND state != 'released' ORDER BY assignment_id",
                    (run_uri,),
                )
            )
            return tuple(self._record(row) for row in rows)

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
        if descriptor is None:
            raise QueueConflictError("SLURM input transfer is not authorized")
        with _connect(self.path, require_existing=True) as conn:
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
        with self._transaction() as conn:
            row = conn.execute(
                f"SELECT descriptor_json, received_bytes, finalized FROM {_OUTPUT_TABLE} "
                "WHERE assignment_id = ? AND transfer_id = ?",
                (assignment_id, transfer_id),
            ).fetchone()
            if row is None:
                raise QueueConflictError("SLURM output transfer is not declared")
            descriptor = _RemoteOutputArtifact.from_dict(json.loads(str(row[0])))
            target = (
                self.transfer_root / assignment_id / "outputs" / descriptor.logical_name
            )
            part = (
                self.transfer_root / assignment_id / "staging" / f"{transfer_id}.part"
            )
            received = int(row["received_bytes"])
            if bool(row["finalized"]):
                existing = _read_regular_file_range(target, offset, len(data))
                if existing != data:
                    raise QueueConflictError("SLURM output replay conflicts")
                return descriptor.size_bytes
            if _published_file_matches(
                target,
                size_bytes=descriptor.size_bytes,
                digest=descriptor.digest,
            ):
                if offset + len(data) > descriptor.size_bytes:
                    raise QueueConflictError("SLURM output replay exceeds its size")
                existing = _read_regular_file_range(target, offset, len(data))
                if existing != data:
                    raise QueueConflictError("SLURM output replay conflicts")
                conn.execute(
                    f"UPDATE {_OUTPUT_TABLE} SET received_bytes = ?, finalized = 1 "
                    "WHERE assignment_id = ? AND transfer_id = ?",
                    (descriptor.size_bytes, assignment_id, transfer_id),
                )
                return descriptor.size_bytes
            received = _append_exact_chunk(part, offset, received, data)
            if received > descriptor.size_bytes:
                raise QueueConflictError("SLURM output exceeds its declared size")
            should_finalize = final or received == descriptor.size_bytes
            if should_finalize:
                if (
                    received != descriptor.size_bytes
                    or _file_digest(part) != descriptor.digest
                ):
                    raise QueueConflictError(
                        "SLURM output bytes conflict with manifest"
                    )
                _publish_staged_file(part, target)
            conn.execute(
                f"UPDATE {_OUTPUT_TABLE} SET received_bytes = ?, finalized = ? "
                "WHERE assignment_id = ? AND transfer_id = ?",
                (received, int(should_finalize), assignment_id, transfer_id),
            )
        return received

    def committed_result(
        self, assignment_id: str, incarnation: str, fence: str
    ) -> tuple[_RemoteExecutionReport, Mapping[str, ArtifactRef]]:
        record = self.read(assignment_id)
        if record.bootstrap_incarnation != incarnation or record.fence != fence:
            raise QueueConflictError("SLURM result authorization conflicts")
        if record.report is None:
            raise QueueConflictError("SLURM result is not declared")
        with _connect(self.path, require_existing=True) as conn:
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

    def release(self, assignment_id: str) -> None:
        record = self.read(assignment_id)
        if record.state == "released":
            return
        self.advance(assignment_id, expected="logical_released", next_state="released")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        if not self.path.is_file():
            if not self._allow_initialize:
                raise QueueServiceError("SLURM assignment store is missing")
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with _connect(self.path, require_existing=not self._allow_initialize) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            if self._allow_initialize:
                existing = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                    (_ASSIGNMENT_TABLE,),
                ).fetchone()
                conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {_ASSIGNMENT_TABLE} ("
                    "assignment_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL UNIQUE, "
                    "run_uri TEXT NOT NULL, stage_work_id TEXT NOT NULL, "
                    "profile_id TEXT NOT NULL, state TEXT NOT NULL, "
                    "identity_json TEXT NOT NULL, request_json TEXT NOT NULL, "
                    "delivery_json TEXT NOT NULL, input_paths_json TEXT NOT NULL, "
                    "issuer_epoch TEXT NOT NULL, job_id TEXT, cluster TEXT, "
                    "bootstrap_incarnation TEXT, input_ready INTEGER NOT NULL, "
                    "fence TEXT, process_execution_id TEXT, report_json TEXT, "
                    "capability_verifier TEXT, submission_eligible INTEGER NOT NULL, "
                    "capability_consumed INTEGER NOT NULL)"
                )
                conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {_OUTPUT_TABLE} ("
                    "assignment_id TEXT NOT NULL, transfer_id TEXT NOT NULL, "
                    "descriptor_json TEXT NOT NULL, received_bytes INTEGER NOT NULL, "
                    "finalized INTEGER NOT NULL, "
                    "PRIMARY KEY (assignment_id, transfer_id))"
                )
                _require_schema(conn, allow_unversioned=existing is None)
                conn.execute("PRAGMA user_version = 3")
            else:
                _require_schema(conn)
            try:
                yield conn
            except Exception:
                conn.rollback()
                raise
            else:
                conn.commit()

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
            delivery=SlurmStageDelivery.from_dict(
                json.loads(str(row["delivery_json"]))
            ),
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
        )


class SlurmBootstrapWorkspace:
    """Bootstrap-owned durable inputs and retained output bytes."""

    def __init__(self, root: str | Path, assignment_id: str) -> None:
        _identifier(assignment_id, "assignment_id")
        self.root = Path(root).resolve() / "assignments" / assignment_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)
        self._delivery_path = self.root / "delivery.json"
        self._registration_path = self.root / "registration.json"
        self._retained_report_path = self.root / "retained-report.json"

    def persist_delivery(self, delivery: SlurmStageDelivery) -> None:
        if delivery.assignment_id != self.root.name:
            raise QueueConflictError("SLURM delivery targets another workspace")
        encoded = (_json(delivery.to_dict()) + "\n").encode()
        if self._delivery_path.exists():
            if self._delivery_path.read_bytes() != encoded:
                raise QueueConflictError("SLURM delivery replay conflicts")
            return
        _atomic_regular_file(self._delivery_path, encoded)
        self._delivery_path.chmod(0o600)

    def persist_registration(self, registration: Mapping[str, PlainData]) -> None:
        """Persist the exact non-secret consume response before file unlink."""
        encoded = (_json(registration) + "\n").encode()
        if self._registration_path.exists():
            if self._registration_path.read_bytes() != encoded:
                raise QueueConflictError("SLURM registration replay conflicts")
            return
        _atomic_regular_file(self._registration_path, encoded)
        self._registration_path.chmod(0o600)

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
        if item is None:
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

    def accept_inputs(self) -> None:
        for item in self.delivery().inputs:
            path = self.root / "inputs" / item.logical_name
            if not _published_file_matches(
                path, size_bytes=item.size_bytes, digest=item.digest
            ):
                raise QueueConflictError("SLURM inputs are not durable")

    def worker_request(self) -> StageWorkerRequest:
        self.accept_inputs()
        return self.delivery().worker_request(self.root)

    def retain_result(self, result: StageWorkerResult) -> _RemoteExecutionReport:
        delivery = self.delivery()
        if (
            result.run_uri != f"loom-slurm:{delivery.assignment_id}"
            or result.stage_name != delivery.stage_name
            or result.attempt != delivery.attempt
        ):
            raise QueueConflictError("SLURM worker result identity conflicts")
        outputs: list[_RemoteOutputArtifact] = []
        if result.status is StageStatus.SUCCEEDED:
            if set(result.outputs) != set(delivery.declared_outputs):
                raise QueueConflictError("SLURM worker outputs conflict")
            for logical_name, ref in sorted(result.outputs.items()):
                source = uri_to_path(ref.uri).resolve(strict=True)
                source.relative_to(self.root)
                data = _read_regular_file_bytes(source)
                digest = hashlib.sha256(data).hexdigest()
                if ref.checksum is not None and ref.checksum != f"sha256:{digest}":
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
                    )
                )
        failure = cast(ExecutionFailure | None, result.failure)
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
            message=None if failure is None else "resident stage execution failed",
            exception_type=None if failure is None else failure.exception_type,
            exit_code=result.exit_code,
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


def _connect(path: Path, *, require_existing: bool = False) -> sqlite3.Connection:
    target: str | Path = (
        f"{path.resolve().as_uri()}?mode=rw" if require_existing else path
    )
    return sqlite3.connect(target, uri=require_existing)


def _require_schema(
    conn: sqlite3.Connection, *, allow_unversioned: bool = False
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
    }
    columns = {
        str(row[1]) for row in conn.execute(f"PRAGMA table_info({_ASSIGNMENT_TABLE})")
    }
    output_columns = {
        str(row[1]) for row in conn.execute(f"PRAGMA table_info({_OUTPUT_TABLE})")
    }
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if (
        (version != 3 and not (allow_unversioned and version == 0))
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
