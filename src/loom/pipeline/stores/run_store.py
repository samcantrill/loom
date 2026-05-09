"""Run-store protocol contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast, runtime_checkable

from loom.artifacts import ArtifactRef
from loom.pipeline.events import PipelineEvent, PipelineEventRecord
from loom.pipeline.locks import RunLockRecord
from loom.pipeline.submitted import SubmittedOperationRecord
from loom.pipeline.status import RunStatusRecord, StageStatusRecord
from loom.pipeline.stores.inspection import RunStateInspection
from loom.serialization import PlainData
from loom.timestamps import parse_timestamp


RUN_FRESHNESS_SCHEMA_VERSION = 1


class RunFreshnessError(ValueError):
    """Raised when run-store freshness metadata is invalid."""


@dataclass(frozen=True, slots=True)
class RunFreshnessRecord:
    """Run-local mutation signal for catalog-relevant metadata."""

    run_uri: str
    token: str
    updated_at: str
    revision: int
    reason: str | None = None
    schema_version: int = RUN_FRESHNESS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_non_empty_string(self.run_uri, "run_uri")
        _validate_non_empty_string(self.token, "token")
        _validate_timestamp(self.updated_at, "updated_at")
        if not isinstance(self.revision, int) or isinstance(self.revision, bool):
            raise RunFreshnessError("revision must be a positive integer")
        if self.revision <= 0:
            raise RunFreshnessError("revision must be a positive integer")
        if self.reason is not None:
            _validate_non_empty_string(self.reason, "reason")
        if self.schema_version != RUN_FRESHNESS_SCHEMA_VERSION:
            raise RunFreshnessError(
                f"unsupported schema_version '{self.schema_version}', expected "
                f"{RUN_FRESHNESS_SCHEMA_VERSION}"
            )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "run_uri": self.run_uri,
            "token": self.token,
            "updated_at": self.updated_at,
            "revision": self.revision,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: object) -> "RunFreshnessRecord":
        if not isinstance(data, Mapping):
            raise RunFreshnessError("RunFreshnessRecord.from_dict expects mapping")
        allowed = {
            "schema_version",
            "run_uri",
            "token",
            "updated_at",
            "revision",
            "reason",
        }
        unknown = set(data) - allowed
        if unknown:
            raise RunFreshnessError(
                "RunFreshnessRecord.from_dict received unknown fields: "
                f"{', '.join(sorted(unknown))}"
            )
        missing = {
            "schema_version",
            "run_uri",
            "token",
            "updated_at",
            "revision",
        } - set(data)
        if missing:
            raise RunFreshnessError(
                "RunFreshnessRecord.from_dict missing required field(s): "
                f"{', '.join(sorted(missing))}"
            )
        return cls(
            schema_version=_validate_schema_version(data["schema_version"]),
            run_uri=_require_string(data["run_uri"], "run_uri"),
            token=_require_string(data["token"], "token"),
            updated_at=_require_string(data["updated_at"], "updated_at"),
            revision=_require_int(data["revision"], "revision"),
            reason=_optional_string(data.get("reason"), "reason"),
        )


def _validate_schema_version(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise RunFreshnessError("schema_version must be a positive integer")
    if value != RUN_FRESHNESS_SCHEMA_VERSION:
        raise RunFreshnessError(
            f"unsupported schema_version '{value}', expected "
            f"{RUN_FRESHNESS_SCHEMA_VERSION}"
        )
    return value


def _require_string(value: object, field: str) -> str:
    _validate_non_empty_string(value, field)
    return cast(str, value)


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field)


def _require_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise RunFreshnessError(f"{field} must be a positive integer")
    return value


def _validate_non_empty_string(value: object, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise RunFreshnessError(f"{field} must be a non-empty string")


def _validate_timestamp(value: object, field: str) -> None:
    if not isinstance(value, str):
        raise RunFreshnessError(f"{field} must be a string")
    try:
        parse_timestamp(value)
    except ValueError as exc:
        raise RunFreshnessError(f"{field} must be a valid loom timestamp") from exc


@runtime_checkable
class RunLifecycleStore(Protocol):
    def create_run(
        self, run_uri: str, *, metadata: Mapping[str, PlainData] | None = None
    ) -> None: ...

    def open_run(self, run_uri: str) -> None: ...

    def resolve_run_uri(self, run_uri: str) -> str: ...

    def allocate_run_uri(self) -> str: ...


@runtime_checkable
class RunDocumentStore(Protocol):
    def read_run_document(self, run_uri: str) -> dict[str, PlainData]: ...

    def read_run_user_metadata(self, run_uri: str) -> dict[str, PlainData]: ...

    def write_run_user_metadata(
        self, run_uri: str, metadata: Mapping[str, PlainData]
    ) -> None: ...


@runtime_checkable
class RunFreshnessStore(Protocol):
    def read_run_freshness(self, run_uri: str) -> RunFreshnessRecord | None: ...


@runtime_checkable
class RunStatusStore(Protocol):
    def read_run_status(self, run_uri: str) -> RunStatusRecord | None: ...

    def write_run_status(self, run_uri: str, status: RunStatusRecord) -> None: ...


@runtime_checkable
class RunPlanStore(Protocol):
    def read_plan(self, run_uri: str) -> dict[str, PlainData] | None: ...

    def write_plan(self, run_uri: str, plan: Mapping[str, PlainData]) -> None: ...


@runtime_checkable
class RunPreparedRunStore(Protocol):
    def read_prepared_run(self, run_uri: str) -> dict[str, PlainData] | None: ...

    def write_prepared_run(
        self, run_uri: str, prepared_run: Mapping[str, PlainData]
    ) -> None: ...


@runtime_checkable
class RunRuntimeMetadataStore(Protocol):
    def read_runtime_metadata(self, run_uri: str) -> dict[str, PlainData] | None: ...

    def write_runtime_metadata(
        self, run_uri: str, metadata: Mapping[str, PlainData]
    ) -> None: ...


@runtime_checkable
class RunSubmittedOperationStore(Protocol):
    def write_submitted_operation(
        self, run_uri: str, record: SubmittedOperationRecord
    ) -> None: ...

    def read_submitted_operation(
        self, run_uri: str, submission_id: str
    ) -> SubmittedOperationRecord | None: ...

    def list_submitted_operations(
        self, run_uri: str
    ) -> tuple[SubmittedOperationRecord, ...]: ...

    def latest_submitted_operation(
        self, run_uri: str
    ) -> SubmittedOperationRecord | None: ...

    def latest_active_submitted_operation(
        self, run_uri: str
    ) -> SubmittedOperationRecord | None: ...


@runtime_checkable
class RunArtifactIndexStore(Protocol):
    def read_artifact_index(self, run_uri: str) -> dict[str, ArtifactRef]: ...

    def write_artifact_index(
        self, run_uri: str, index: Mapping[str, ArtifactRef]
    ) -> None: ...


@runtime_checkable
class RunConfigStore(Protocol):
    def read_config_snapshot(self, run_uri: str, name: str) -> str | None: ...

    def write_config_snapshot(self, run_uri: str, name: str, content: str) -> None: ...

    def read_composition_manifest(
        self, run_uri: str
    ) -> dict[str, PlainData] | None: ...

    def write_composition_manifest(
        self, run_uri: str, manifest: Mapping[str, PlainData]
    ) -> None: ...

    def read_recipe_manifest(
        self, run_uri: str
    ) -> tuple[dict[str, PlainData], ...] | None: ...

    def write_recipe_manifest(
        self, run_uri: str, records: Sequence[Mapping[str, PlainData]]
    ) -> None: ...


@runtime_checkable
class RunProvenanceStore(Protocol):
    def read_provenance_document(
        self, run_uri: str, name: str
    ) -> dict[str, PlainData] | None: ...

    def write_provenance_document(
        self, run_uri: str, name: str, document: Mapping[str, PlainData]
    ) -> None: ...


@runtime_checkable
class RunEventStore(Protocol):
    def append_event(
        self, run_uri: str, event: PipelineEvent
    ) -> PipelineEventRecord: ...

    def read_events(self, run_uri: str) -> tuple[PipelineEventRecord, ...]: ...


@runtime_checkable
class RunLockStore(Protocol):
    def acquire_run_lock(
        self,
        run_uri: str,
        *,
        owner: Mapping[str, PlainData] | None = None,
    ) -> RunLockRecord: ...

    def read_run_lock(self, run_uri: str) -> RunLockRecord | None: ...

    def release_run_lock(self, run_uri: str, token: str) -> None: ...


@runtime_checkable
class RunInspectionStore(Protocol):
    def list_run_stages(self, run_uri: str) -> tuple[str, ...]: ...

    def inspect_run_state(self, run_uri: str) -> RunStateInspection: ...


@runtime_checkable
class StageStateStore(Protocol):
    def read_stage_status(
        self, run_uri: str, stage_name: str
    ) -> StageStatusRecord | None: ...

    def write_stage_status(
        self, run_uri: str, stage_name: str, status: StageStatusRecord
    ) -> None: ...

    def read_stage_inputs(
        self, run_uri: str, stage_name: str
    ) -> dict[str, ArtifactRef] | None: ...

    def write_stage_inputs(
        self,
        run_uri: str,
        stage_name: str,
        inputs: Mapping[str, ArtifactRef],
        *,
        attempt: int,
    ) -> None: ...

    def read_stage_outputs(
        self, run_uri: str, stage_name: str
    ) -> dict[str, ArtifactRef] | None: ...

    def write_stage_outputs(
        self,
        run_uri: str,
        stage_name: str,
        outputs: Mapping[str, ArtifactRef],
        *,
        attempt: int,
    ) -> None: ...

    def read_stage_fingerprint(
        self, run_uri: str, stage_name: str
    ) -> dict[str, PlainData] | None: ...

    def write_stage_fingerprint(
        self,
        run_uri: str,
        stage_name: str,
        fingerprint: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None: ...

    def read_stage_failure(
        self, run_uri: str, stage_name: str
    ) -> dict[str, PlainData] | None: ...

    def write_stage_failure(
        self,
        run_uri: str,
        stage_name: str,
        failure: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None: ...

    def read_stage_worker_request(
        self, run_uri: str, stage_name: str, *, attempt: int
    ) -> dict[str, PlainData] | None: ...

    def write_stage_worker_request(
        self,
        run_uri: str,
        stage_name: str,
        request: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None: ...

    def read_stage_worker_result(
        self, run_uri: str, stage_name: str, *, attempt: int
    ) -> dict[str, PlainData] | None: ...

    def write_stage_worker_result(
        self,
        run_uri: str,
        stage_name: str,
        result: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None: ...

    def read_stage_provenance(
        self, run_uri: str, stage_name: str
    ) -> dict[str, PlainData] | None: ...

    def write_stage_provenance(
        self,
        run_uri: str,
        stage_name: str,
        provenance: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None: ...


@runtime_checkable
class StageLogStore(Protocol):
    def read_stage_log(
        self, run_uri: str, stage_name: str, stream: str
    ) -> str | None: ...

    def write_stage_log(
        self, run_uri: str, stage_name: str, stream: str, content: str
    ) -> None: ...


@runtime_checkable
class StageWorkspaceStore(Protocol):
    def prepare_stage_workspace(self, run_uri: str, stage_name: str) -> None: ...


@runtime_checkable
class LocalRunStorePaths(Protocol):
    def resolve_run_uri(self, run_uri: str) -> str: ...

    def allocate_run_uri(self) -> str: ...

    def local_run_dir(self, run_uri: str) -> Path: ...

    def local_stage_dir(self, run_uri: str, stage_name: str) -> Path: ...

    def local_artifact_root(self, run_uri: str) -> Path: ...

    def local_stage_artifact_dir(self, run_uri: str, stage_name: str) -> Path: ...

    def local_config_path(self, run_uri: str, name: str) -> Path: ...

    def local_provenance_path(self, run_uri: str, name: str) -> Path: ...

    def local_stage_log_path(
        self, run_uri: str, stage_name: str, stream: str
    ) -> Path: ...

    def local_stage_worker_request_path(
        self, run_uri: str, stage_name: str
    ) -> Path: ...

    def local_stage_worker_result_path(self, run_uri: str, stage_name: str) -> Path: ...

    def local_stage_workspace_dir(self, run_uri: str, stage_name: str) -> Path: ...

    def local_generated_artifact_path(
        self, run_uri: str, relative_path: str
    ) -> Path: ...

    def local_run_freshness_path(self, run_uri: str) -> Path: ...


@runtime_checkable
class RunStore(
    RunLifecycleStore,
    RunDocumentStore,
    RunFreshnessStore,
    RunStatusStore,
    RunPlanStore,
    RunPreparedRunStore,
    RunArtifactIndexStore,
    RunConfigStore,
    RunProvenanceStore,
    RunEventStore,
    RunLockStore,
    RunInspectionStore,
    RunRuntimeMetadataStore,
    RunSubmittedOperationStore,
    StageStateStore,
    StageLogStore,
    StageWorkspaceStore,
    Protocol,
): ...
