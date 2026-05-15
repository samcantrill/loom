"""Execution data models for the local pipeline runtime."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from loom.artifacts import ArtifactRef, ArtifactValidationError
from loom.pipeline.context import StageContext
from loom.pipeline.planning import (
    ExecutionPlan,
    FingerprintContext,
    PlanAction,
    PlanReason,
    PlanSelectors,
    ResumeOptions,
    StageFingerprintRecord,
    StagePlan,
)
from loom.pipeline.runtime import (
    ResolvedStageRuntimeOptions,
    RunOptions,
    parse_run_options,
)
from loom.pipeline.specs import PipelineSpec, StageSpec
from loom.pipeline.stage import Stage
from loom.pipeline.status import RunStatus, StageStatus
from loom.serialization import PlainData, ensure_plain_data, load_versioned_document
from loom.serialization.errors import PlainDataError
from loom.serialization.errors import SchemaVersionError
from .errors import RunRequestError

if TYPE_CHECKING:
    from loom.provenance.models import CommandProvenance, ProvenanceCaptureOptions

EXECUTION_FAILURE_SCHEMA_VERSION = 1
STAGE_WORKER_REQUEST_SCHEMA_VERSION = 1
STAGE_WORKER_RESULT_SCHEMA_VERSION = 1

_VALID_FAILURE_TYPES = {
    "stage_exception",
    "stage_contract",
    "output_validation",
    "target_construction",
    "plan_execution",
    "resource_admission",
    "store_commit",
    "executor_infrastructure",
}


class _ComposedConfigLike(Protocol):
    @property
    def resolved(self) -> Mapping[str, PlainData]: ...

    @property
    def redacted(self) -> Mapping[str, PlainData]: ...

    @property
    def manifest(self) -> object: ...

    @property
    def provenance(self) -> object: ...

    @property
    def recipe_manifest(self) -> Sequence[Mapping[str, PlainData]]: ...


@dataclass(frozen=True, slots=True)
class ConfigSnapshotInputs:
    raw: str | None = None
    overlays: str | None = None
    cli_overrides: str | None = None

    def __post_init__(self) -> None:
        for name in ("raw", "overlays", "cli_overrides"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise RunRequestError(
                    f"ConfigSnapshotInputs.{name} must be a string when set"
                )


@dataclass(frozen=True, slots=True)
class FailurePolicy:
    stop_on_first_failure: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.stop_on_first_failure, bool):
            raise RunRequestError("FailurePolicy.stop_on_first_failure must be a bool")


@dataclass(frozen=True, slots=True)
class RunRequest:
    config: _ComposedConfigLike | Mapping[str, PlainData] | None = None
    pipeline: PipelineSpec | None = None
    run_uri: str | None = None
    open_existing: bool = False
    options: RunOptions | Mapping[str, object] = field(default_factory=RunOptions)
    selectors: PlanSelectors = field(default_factory=PlanSelectors)
    resume: ResumeOptions = field(default_factory=ResumeOptions)
    fingerprint_context: FingerprintContext = field(default_factory=FingerprintContext)
    config_snapshots: ConfigSnapshotInputs = field(default_factory=ConfigSnapshotInputs)
    provenance_options: ProvenanceCaptureOptions = field(
        default_factory=lambda: _default_provenance_options()
    )
    command: CommandProvenance | None = None
    project_root: Path | None = None
    failure_policy: FailurePolicy = field(default_factory=FailurePolicy)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.config is None and self.pipeline is None:
            raise RunRequestError("RunRequest requires either config or pipeline")
        if self.config is not None and not (
            isinstance(self.config, Mapping) or _is_composed_config(self.config)
        ):
            raise RunRequestError(
                "RunRequest.config must be a ComposedConfig or mapping"
            )
        if self.pipeline is not None and not isinstance(self.pipeline, PipelineSpec):
            raise RunRequestError(
                "RunRequest.pipeline must be a PipelineSpec when supplied"
            )
        if not isinstance(self.open_existing, bool):
            raise RunRequestError("RunRequest.open_existing must be a bool")

        selectors = _coerce_selectors(self.selectors)
        resume = _coerce_resume(self.resume)
        if self.run_uri is not None and (
            not isinstance(self.run_uri, str) or not self.run_uri
        ):
            raise RunRequestError("RunRequest.run_uri must be a non-empty string")
        options = _normalize_run_request_options(
            self.options,
            run_uri=self.run_uri,
            selectors=selectors,
            resume=resume,
        )
        object.__setattr__(self, "options", options)
        object.__setattr__(self, "run_uri", options.run_uri)
        object.__setattr__(self, "selectors", options.to_plan_selectors())
        object.__setattr__(self, "resume", options.to_resume_options())
        object.__setattr__(
            self,
            "fingerprint_context",
            _coerce_fingerprint_context(self.fingerprint_context),
        )
        object.__setattr__(
            self,
            "config_snapshots",
            _coerce_config_snapshots(self.config_snapshots),
        )
        object.__setattr__(
            self,
            "provenance_options",
            _coerce_provenance_options(self.provenance_options),
        )
        if self.command is not None and not _is_command_provenance(self.command):
            raise RunRequestError(
                "RunRequest.command must be CommandProvenance when supplied"
            )
        if self.project_root is not None:
            object.__setattr__(self, "project_root", Path(self.project_root))
        object.__setattr__(
            self, "failure_policy", _coerce_failure_policy(self.failure_policy)
        )
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))


@dataclass(frozen=True, slots=True)
class ExecutionFailure:
    schema_version: int
    run_uri: str
    stage_name: str
    attempt: int
    failed_at: str
    executor: str
    failure_type: str
    message: str
    exception_type: str | None = None
    traceback_path: str | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    exit_code: int | None = None
    signal: int | None = None
    executor_metadata: Mapping[str, PlainData] = field(default_factory=dict)
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != EXECUTION_FAILURE_SCHEMA_VERSION:
            raise RunRequestError("ExecutionFailure.schema_version must be 1")
        if not isinstance(self.run_uri, str) or not self.run_uri:
            raise RunRequestError("ExecutionFailure.run_uri must be a non-empty string")
        if not isinstance(self.stage_name, str) or not self.stage_name:
            raise RunRequestError(
                "ExecutionFailure.stage_name must be a non-empty string"
            )
        if (
            not isinstance(self.attempt, int)
            or isinstance(self.attempt, bool)
            or self.attempt <= 0
        ):
            raise RunRequestError("ExecutionFailure.attempt must be a positive integer")
        if not isinstance(self.failed_at, str) or not self.failed_at:
            raise RunRequestError(
                "ExecutionFailure.failed_at must be a non-empty string"
            )
        if not isinstance(self.executor, str) or not self.executor:
            raise RunRequestError(
                "ExecutionFailure.executor must be a non-empty string"
            )
        if self.failure_type not in _VALID_FAILURE_TYPES:
            valid = ", ".join(sorted(_VALID_FAILURE_TYPES))
            raise RunRequestError(
                f"ExecutionFailure.failure_type must be one of: {valid}"
            )
        if not isinstance(self.message, str) or not self.message:
            raise RunRequestError("ExecutionFailure.message must be a non-empty string")
        if self.exception_type is not None and not isinstance(self.exception_type, str):
            raise RunRequestError(
                "ExecutionFailure.exception_type must be a string when set"
            )
        for name in ("traceback_path", "stdout_path", "stderr_path"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise RunRequestError(
                    f"ExecutionFailure.{name} must be a string when set"
                )
        if self.exit_code is not None and (
            not isinstance(self.exit_code, int) or isinstance(self.exit_code, bool)
        ):
            raise RunRequestError(
                "ExecutionFailure.exit_code must be an integer when set"
            )
        if self.signal is not None and (
            not isinstance(self.signal, int)
            or isinstance(self.signal, bool)
            or self.signal <= 0
        ):
            raise RunRequestError(
                "ExecutionFailure.signal must be a positive integer when set"
            )
        if self.signal is not None and self.exit_code is not None:
            raise RunRequestError(
                "ExecutionFailure.exit_code and signal must not both be set"
            )
        object.__setattr__(
            self,
            "executor_metadata",
            _plain_mapping(self.executor_metadata, "executor_metadata"),
        )
        object.__setattr__(self, "details", _plain_mapping(self.details, "details"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "run_uri": self.run_uri,
            "stage_name": self.stage_name,
            "attempt": self.attempt,
            "failed_at": self.failed_at,
            "executor": self.executor,
            "failure_type": self.failure_type,
            "message": self.message,
            "exception_type": self.exception_type,
            "traceback_path": self.traceback_path,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "exit_code": self.exit_code,
            "signal": self.signal,
            "executor_metadata": dict(self.executor_metadata),
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, data: object) -> "ExecutionFailure":
        try:
            mapping = load_versioned_document(
                data,
                current_version=EXECUTION_FAILURE_SCHEMA_VERSION,
                required={
                    "run_uri",
                    "stage_name",
                    "attempt",
                    "failed_at",
                    "executor",
                    "failure_type",
                    "message",
                },
                optional={
                    "exception_type",
                    "traceback_path",
                    "stdout_path",
                    "stderr_path",
                    "exit_code",
                    "signal",
                    "executor_metadata",
                    "details",
                },
            )
        except SchemaVersionError as exc:
            raise RunRequestError(f"ExecutionFailure.from_dict: {exc}") from exc

        return cls(
            schema_version=_int(mapping["schema_version"], "schema_version"),
            run_uri=_str(mapping["run_uri"], "run_uri"),
            stage_name=_str(mapping["stage_name"], "stage_name"),
            attempt=_int(mapping["attempt"], "attempt"),
            failed_at=_str(mapping["failed_at"], "failed_at"),
            executor=_str(mapping["executor"], "executor"),
            failure_type=_str(mapping["failure_type"], "failure_type"),
            message=_str(mapping["message"], "message"),
            exception_type=_optional_str(
                mapping.get("exception_type"), "exception_type"
            ),
            traceback_path=_optional_str(
                mapping.get("traceback_path"), "traceback_path"
            ),
            stdout_path=_optional_str(mapping.get("stdout_path"), "stdout_path"),
            stderr_path=_optional_str(mapping.get("stderr_path"), "stderr_path"),
            exit_code=_optional_int(mapping.get("exit_code"), "exit_code"),
            signal=_optional_int(mapping.get("signal"), "signal"),
            executor_metadata=_plain_mapping(
                cast(Mapping[str, PlainData], mapping.get("executor_metadata", {})),
                "executor_metadata",
            ),
            details=_plain_mapping(
                cast(Mapping[str, PlainData], mapping.get("details", {})), "details"
            ),
        )


@dataclass(frozen=True, slots=True)
class StageWorkerRequest:
    schema_version: int
    run_uri: str
    stage_name: str
    attempt: int
    prepared_at: str
    executor_name: str
    inputs: Mapping[str, ArtifactRef]
    fingerprint: StageFingerprintRecord | Mapping[str, PlainData]
    stdout_path: str
    stderr_path: str
    traceback_path: str
    result_path: str
    resolved_runtime: Mapping[str, PlainData]
    executor_metadata: Mapping[str, PlainData] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != STAGE_WORKER_REQUEST_SCHEMA_VERSION:
            raise RunRequestError("StageWorkerRequest.schema_version must be 1")
        if not isinstance(self.run_uri, str) or not self.run_uri:
            raise RunRequestError(
                "StageWorkerRequest.run_uri must be a non-empty string"
            )
        if not isinstance(self.stage_name, str) or not self.stage_name:
            raise RunRequestError(
                "StageWorkerRequest.stage_name must be a non-empty string"
            )
        if (
            not isinstance(self.attempt, int)
            or isinstance(self.attempt, bool)
            or self.attempt <= 0
        ):
            raise RunRequestError("StageWorkerRequest.attempt must be positive")
        if not isinstance(self.prepared_at, str) or not self.prepared_at:
            raise RunRequestError(
                "StageWorkerRequest.prepared_at must be a non-empty string"
            )
        if not isinstance(self.executor_name, str) or not self.executor_name:
            raise RunRequestError(
                "StageWorkerRequest.executor_name must be a non-empty string"
            )
        for name in ("stdout_path", "stderr_path", "traceback_path", "result_path"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise RunRequestError(
                    f"StageWorkerRequest.{name} must be a non-empty string"
                )
        object.__setattr__(self, "inputs", _artifact_ref_mapping(self.inputs, "inputs"))
        object.__setattr__(
            self,
            "fingerprint",
            _coerce_fingerprint_record(self.fingerprint, "fingerprint"),
        )
        runtime = _plain_mapping(self.resolved_runtime, "resolved_runtime")
        stage_id = runtime.get("stage_id")
        if stage_id != self.stage_name:
            raise RunRequestError(
                "StageWorkerRequest.resolved_runtime.stage_id must match stage_name"
            )
        if "executor" not in runtime:
            raise RunRequestError(
                "StageWorkerRequest.resolved_runtime must include executor"
            )
        object.__setattr__(self, "resolved_runtime", runtime)
        object.__setattr__(
            self,
            "executor_metadata",
            _plain_mapping(self.executor_metadata, "executor_metadata"),
        )
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, PlainData]:
        fingerprint = cast(StageFingerprintRecord, self.fingerprint)
        return {
            "schema_version": self.schema_version,
            "run_uri": self.run_uri,
            "stage_name": self.stage_name,
            "attempt": self.attempt,
            "prepared_at": self.prepared_at,
            "executor_name": self.executor_name,
            "inputs": {name: ref.to_dict() for name, ref in self.inputs.items()},
            "fingerprint": fingerprint.to_dict(),
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "traceback_path": self.traceback_path,
            "result_path": self.result_path,
            "resolved_runtime": dict(self.resolved_runtime),
            "executor_metadata": dict(self.executor_metadata),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "StageWorkerRequest":
        try:
            mapping = load_versioned_document(
                data,
                current_version=STAGE_WORKER_REQUEST_SCHEMA_VERSION,
                required={
                    "run_uri",
                    "stage_name",
                    "attempt",
                    "prepared_at",
                    "executor_name",
                    "inputs",
                    "fingerprint",
                    "stdout_path",
                    "stderr_path",
                    "traceback_path",
                    "result_path",
                    "resolved_runtime",
                },
                optional={"executor_metadata", "metadata"},
            )
        except SchemaVersionError as exc:
            raise RunRequestError(f"StageWorkerRequest.from_dict: {exc}") from exc
        return cls(
            schema_version=_int(mapping["schema_version"], "schema_version"),
            run_uri=_str(mapping["run_uri"], "run_uri"),
            stage_name=_str(mapping["stage_name"], "stage_name"),
            attempt=_int(mapping["attempt"], "attempt"),
            prepared_at=_str(mapping["prepared_at"], "prepared_at"),
            executor_name=_str(mapping["executor_name"], "executor_name"),
            inputs=_artifact_ref_mapping(
                _object_mapping(mapping["inputs"], "inputs"),
                "inputs",
            ),
            fingerprint=_plain_mapping(
                cast(Mapping[str, PlainData], mapping["fingerprint"]),
                "fingerprint",
            ),
            stdout_path=_str(mapping["stdout_path"], "stdout_path"),
            stderr_path=_str(mapping["stderr_path"], "stderr_path"),
            traceback_path=_str(mapping["traceback_path"], "traceback_path"),
            result_path=_str(mapping["result_path"], "result_path"),
            resolved_runtime=_plain_mapping(
                cast(Mapping[str, PlainData], mapping["resolved_runtime"]),
                "resolved_runtime",
            ),
            executor_metadata=_plain_mapping(
                cast(Mapping[str, PlainData], mapping.get("executor_metadata", {})),
                "executor_metadata",
            ),
            metadata=_plain_mapping(
                cast(Mapping[str, PlainData], mapping.get("metadata", {})),
                "metadata",
            ),
        )


@dataclass(frozen=True, slots=True)
class StageWorkerResult:
    schema_version: int
    run_uri: str
    stage_name: str
    attempt: int
    status: StageStatus
    started_at: str
    finished_at: str
    executor_name: str
    outputs: Mapping[str, ArtifactRef] = field(default_factory=dict)
    failure: ExecutionFailure | Mapping[str, PlainData] | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    traceback_path: str | None = None
    exit_code: int | None = None
    signal: int | None = None
    executor_metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != STAGE_WORKER_RESULT_SCHEMA_VERSION:
            raise RunRequestError("StageWorkerResult.schema_version must be 1")
        if not isinstance(self.run_uri, str) or not self.run_uri:
            raise RunRequestError(
                "StageWorkerResult.run_uri must be a non-empty string"
            )
        if not isinstance(self.stage_name, str) or not self.stage_name:
            raise RunRequestError(
                "StageWorkerResult.stage_name must be a non-empty string"
            )
        if (
            not isinstance(self.attempt, int)
            or isinstance(self.attempt, bool)
            or self.attempt <= 0
        ):
            raise RunRequestError("StageWorkerResult.attempt must be positive")
        object.__setattr__(self, "status", _stage_status(self.status))
        if self.status not in {
            StageStatus.SUCCEEDED,
            StageStatus.FAILED,
            StageStatus.CANCELLED,
        }:
            raise RunRequestError(
                "StageWorkerResult.status must be SUCCEEDED, FAILED, or CANCELLED"
            )
        if not isinstance(self.started_at, str) or not self.started_at:
            raise RunRequestError(
                "StageWorkerResult.started_at must be a non-empty string"
            )
        if not isinstance(self.finished_at, str) or not self.finished_at:
            raise RunRequestError(
                "StageWorkerResult.finished_at must be a non-empty string"
            )
        if not isinstance(self.executor_name, str) or not self.executor_name:
            raise RunRequestError(
                "StageWorkerResult.executor_name must be a non-empty string"
            )
        for name in ("stdout_path", "stderr_path", "traceback_path"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise RunRequestError(
                    f"StageWorkerResult.{name} must be a string when set"
                )
        if self.exit_code is not None and (
            not isinstance(self.exit_code, int) or isinstance(self.exit_code, bool)
        ):
            raise RunRequestError("StageWorkerResult.exit_code must be an integer")
        if self.signal is not None and (
            not isinstance(self.signal, int)
            or isinstance(self.signal, bool)
            or self.signal <= 0
        ):
            raise RunRequestError("StageWorkerResult.signal must be a positive integer")
        if self.signal is not None and self.exit_code is not None:
            raise RunRequestError(
                "StageWorkerResult.exit_code and signal must not both be set"
            )
        failure = _optional_execution_failure(self.failure)
        if self.status == StageStatus.SUCCEEDED:
            if failure is not None:
                raise RunRequestError(
                    "StageWorkerResult.failure must be null for SUCCEEDED"
                )
            if self.signal is not None or self.exit_code not in {None, 0}:
                raise RunRequestError(
                    "StageWorkerResult SUCCEEDED cannot carry nonzero process failure metadata"
                )
        if self.status == StageStatus.FAILED and failure is None:
            raise RunRequestError("StageWorkerResult.failure is required for FAILED")
        if self.status == StageStatus.CANCELLED and failure is not None:
            raise RunRequestError("StageWorkerResult.failure must be null for CANCELLED")
        if failure is not None:
            if failure.run_uri != self.run_uri:
                raise RunRequestError("StageWorkerResult.failure.run_uri mismatch")
            if failure.stage_name != self.stage_name:
                raise RunRequestError("StageWorkerResult.failure.stage_name mismatch")
            if failure.attempt != self.attempt:
                raise RunRequestError("StageWorkerResult.failure.attempt mismatch")
        outputs = _artifact_ref_mapping(self.outputs, "outputs")
        if self.status in {StageStatus.FAILED, StageStatus.CANCELLED} and outputs:
            raise RunRequestError(
                "StageWorkerResult FAILED or CANCELLED must not include outputs"
            )
        object.__setattr__(self, "outputs", outputs)
        object.__setattr__(self, "failure", failure)
        object.__setattr__(
            self,
            "executor_metadata",
            _plain_mapping(self.executor_metadata, "executor_metadata"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        failure = cast(ExecutionFailure | None, self.failure)
        return {
            "schema_version": self.schema_version,
            "run_uri": self.run_uri,
            "stage_name": self.stage_name,
            "attempt": self.attempt,
            "status": self.status.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "executor_name": self.executor_name,
            "outputs": {name: ref.to_dict() for name, ref in self.outputs.items()},
            "failure": failure.to_dict() if failure is not None else None,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "traceback_path": self.traceback_path,
            "exit_code": self.exit_code,
            "signal": self.signal,
            "executor_metadata": dict(self.executor_metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "StageWorkerResult":
        try:
            mapping = load_versioned_document(
                data,
                current_version=STAGE_WORKER_RESULT_SCHEMA_VERSION,
                required={
                    "run_uri",
                    "stage_name",
                    "attempt",
                    "status",
                    "started_at",
                    "finished_at",
                    "executor_name",
                    "outputs",
                    "failure",
                },
                optional={
                    "stdout_path",
                    "stderr_path",
                    "traceback_path",
                    "exit_code",
                    "signal",
                    "executor_metadata",
                },
            )
        except SchemaVersionError as exc:
            raise RunRequestError(f"StageWorkerResult.from_dict: {exc}") from exc
        return cls(
            schema_version=_int(mapping["schema_version"], "schema_version"),
            run_uri=_str(mapping["run_uri"], "run_uri"),
            stage_name=_str(mapping["stage_name"], "stage_name"),
            attempt=_int(mapping["attempt"], "attempt"),
            status=_stage_status(_str(mapping["status"], "status")),
            started_at=_str(mapping["started_at"], "started_at"),
            finished_at=_str(mapping["finished_at"], "finished_at"),
            executor_name=_str(mapping["executor_name"], "executor_name"),
            outputs=_artifact_ref_mapping(
                _object_mapping(mapping["outputs"], "outputs"),
                "outputs",
            ),
            failure=_optional_execution_failure(
                cast(
                    ExecutionFailure | Mapping[str, PlainData] | None,
                    mapping.get("failure"),
                )
            ),
            stdout_path=_optional_str(mapping.get("stdout_path"), "stdout_path"),
            stderr_path=_optional_str(mapping.get("stderr_path"), "stderr_path"),
            traceback_path=_optional_str(
                mapping.get("traceback_path"), "traceback_path"
            ),
            exit_code=_optional_int(mapping.get("exit_code"), "exit_code"),
            signal=_optional_int(mapping.get("signal"), "signal"),
            executor_metadata=_plain_mapping(
                cast(Mapping[str, PlainData], mapping.get("executor_metadata", {})),
                "executor_metadata",
            ),
        )


@dataclass(frozen=True, slots=True)
class StageExecutionRequest:
    run_uri: str
    stage: StageSpec
    stage_plan: StagePlan
    stage_object: Stage
    context: StageContext
    inputs: Mapping[str, ArtifactRef]
    fingerprint: StageFingerprintRecord
    attempt: int
    stdout_path: Path
    stderr_path: Path
    traceback_path: Path
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    resolved_runtime: ResolvedStageRuntimeOptions | Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.run_uri, str) or not self.run_uri:
            raise RunRequestError(
                "StageExecutionRequest.run_uri must be a non-empty string"
            )
        if not isinstance(self.stage, StageSpec):
            raise RunRequestError("StageExecutionRequest.stage must be a StageSpec")
        if not isinstance(self.stage_plan, StagePlan):
            raise RunRequestError(
                "StageExecutionRequest.stage_plan must be a StagePlan"
            )
        if not isinstance(self.stage_object, Stage):
            raise RunRequestError(
                "StageExecutionRequest.stage_object must satisfy Stage"
            )
        if not isinstance(self.context, StageContext):
            raise RunRequestError("StageExecutionRequest.context must be StageContext")
        if not isinstance(self.fingerprint, StageFingerprintRecord):
            raise RunRequestError(
                "StageExecutionRequest.fingerprint must be StageFingerprintRecord"
            )
        if (
            not isinstance(self.attempt, int)
            or isinstance(self.attempt, bool)
            or self.attempt <= 0
        ):
            raise RunRequestError(
                "StageExecutionRequest.attempt must be a positive integer"
            )
        object.__setattr__(self, "inputs", _artifact_ref_mapping(self.inputs, "inputs"))
        object.__setattr__(self, "stdout_path", Path(self.stdout_path))
        object.__setattr__(self, "stderr_path", Path(self.stderr_path))
        object.__setattr__(self, "traceback_path", Path(self.traceback_path))
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))
        object.__setattr__(
            self,
            "resolved_runtime",
            _coerce_resolved_runtime(self.resolved_runtime, stage_name=self.stage.name),
        )


@dataclass(frozen=True, slots=True)
class StageExecutionResult:
    stage_name: str
    status: StageStatus
    outputs: Mapping[str, object]
    failure: ExecutionFailure | None
    started_at: str
    finished_at: str
    executor_name: str
    attempt: int
    stdout_path: str | None = None
    stderr_path: str | None = None
    traceback_path: str | None = None
    executor_metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.stage_name, str) or not self.stage_name:
            raise RunRequestError(
                "StageExecutionResult.stage_name must be a non-empty string"
            )
        object.__setattr__(self, "status", _stage_status(self.status))
        if self.status not in {
            StageStatus.SUCCEEDED,
            StageStatus.FAILED,
            StageStatus.CANCELLED,
        }:
            raise RunRequestError(
                "StageExecutionResult.status must be SUCCEEDED, FAILED, or CANCELLED"
            )
        if self.status == StageStatus.CANCELLED and self.failure is not None:
            raise RunRequestError(
                "StageExecutionResult.failure must be null for CANCELLED"
            )
        if self.failure is not None and not isinstance(self.failure, ExecutionFailure):
            raise RunRequestError(
                "StageExecutionResult.failure must be ExecutionFailure when set"
            )
        if not isinstance(self.started_at, str) or not self.started_at:
            raise RunRequestError(
                "StageExecutionResult.started_at must be a non-empty string"
            )
        if not isinstance(self.finished_at, str) or not self.finished_at:
            raise RunRequestError(
                "StageExecutionResult.finished_at must be a non-empty string"
            )
        if not isinstance(self.executor_name, str) or not self.executor_name:
            raise RunRequestError(
                "StageExecutionResult.executor_name must be a non-empty string"
            )
        if (
            not isinstance(self.attempt, int)
            or isinstance(self.attempt, bool)
            or self.attempt <= 0
        ):
            raise RunRequestError(
                "StageExecutionResult.attempt must be a positive integer"
            )
        if not isinstance(self.outputs, Mapping):
            raise RunRequestError("StageExecutionResult.outputs must be a mapping")
        if self.status == StageStatus.CANCELLED and self.outputs:
            raise RunRequestError("StageExecutionResult CANCELLED must not include outputs")
        for name in ("stdout_path", "stderr_path", "traceback_path"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise RunRequestError(
                    f"StageExecutionResult.{name} must be a string when set"
                )
        object.__setattr__(self, "outputs", dict(self.outputs))
        object.__setattr__(
            self,
            "executor_metadata",
            _plain_mapping(self.executor_metadata, "executor_metadata"),
        )


@dataclass(frozen=True, slots=True)
class StageRunResult:
    stage_name: str
    action: PlanAction
    status: StageStatus | None
    attempt: int | None
    outputs: Mapping[str, ArtifactRef]
    failure: ExecutionFailure | None = None
    reasons: tuple[PlanReason, ...] = ()
    started_at: str | None = None
    finished_at: str | None = None
    executor_metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.stage_name, str) or not self.stage_name:
            raise RunRequestError(
                "StageRunResult.stage_name must be a non-empty string"
            )
        object.__setattr__(self, "action", _plan_action(self.action))
        if self.status is not None:
            object.__setattr__(self, "status", _stage_status(self.status))
        if self.attempt is not None and (
            not isinstance(self.attempt, int)
            or isinstance(self.attempt, bool)
            or self.attempt <= 0
        ):
            raise RunRequestError("StageRunResult.attempt must be positive when set")
        object.__setattr__(
            self, "outputs", _artifact_ref_mapping(self.outputs, "outputs")
        )
        if self.failure is not None and not isinstance(self.failure, ExecutionFailure):
            raise RunRequestError(
                "StageRunResult.failure must be ExecutionFailure when set"
            )
        object.__setattr__(self, "reasons", _reason_tuple(self.reasons))
        object.__setattr__(
            self,
            "executor_metadata",
            _plain_mapping(self.executor_metadata, "executor_metadata"),
        )


@dataclass(frozen=True, slots=True)
class RunResult:
    run_uri: str
    status: RunStatus
    started_at: str
    finished_at: str
    plan: ExecutionPlan
    stage_results: Mapping[str, StageRunResult]
    failed_stage: str | None = None
    failure: ExecutionFailure | None = None
    artifact_index: Mapping[str, ArtifactRef] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.run_uri, str) or not self.run_uri:
            raise RunRequestError("RunResult.run_uri must be a non-empty string")
        object.__setattr__(self, "status", _run_status(self.status))
        if not isinstance(self.started_at, str) or not self.started_at:
            raise RunRequestError("RunResult.started_at must be a non-empty string")
        if not isinstance(self.finished_at, str) or not self.finished_at:
            raise RunRequestError("RunResult.finished_at must be a non-empty string")
        if not isinstance(self.plan, ExecutionPlan):
            raise RunRequestError("RunResult.plan must be ExecutionPlan")
        if not isinstance(self.stage_results, Mapping):
            raise RunRequestError("RunResult.stage_results must be a mapping")
        normalized_results: dict[str, StageRunResult] = {}
        for name, result in self.stage_results.items():
            if not isinstance(name, str) or not isinstance(result, StageRunResult):
                raise RunRequestError(
                    "RunResult.stage_results must map strings to StageRunResult"
                )
            normalized_results[name] = result
        if set(normalized_results) != set(self.plan.stage_order):
            raise RunRequestError(
                "RunResult.stage_results must contain every planned stage"
            )
        if self.failed_stage is not None and not isinstance(self.failed_stage, str):
            raise RunRequestError("RunResult.failed_stage must be a string when set")
        if self.failure is not None and not isinstance(self.failure, ExecutionFailure):
            raise RunRequestError("RunResult.failure must be ExecutionFailure when set")
        object.__setattr__(self, "stage_results", normalized_results)
        object.__setattr__(
            self,
            "artifact_index",
            _artifact_ref_mapping(self.artifact_index, "artifact_index"),
        )
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))


def _normalize_run_request_options(
    value: RunOptions | Mapping[str, object],
    *,
    run_uri: str | None,
    selectors: PlanSelectors,
    resume: ResumeOptions,
) -> RunOptions:
    options = _coerce_run_options(value)
    data = options.to_dict()

    if run_uri is not None:
        if options.run_uri is not None and options.run_uri != run_uri:
            raise RunRequestError(
                "RunRequest.run_uri conflicts with RunRequest.options.run_uri"
            )
        data["run_uri"] = run_uri

    option_selectors = options.to_plan_selectors()
    if selectors != PlanSelectors():
        if option_selectors != PlanSelectors() and option_selectors != selectors:
            raise RunRequestError(
                "RunRequest.selectors conflicts with RunRequest.options.selectors"
            )
        data["selectors"] = selectors.to_dict()

    option_resume = options.to_resume_options()
    if resume != ResumeOptions():
        if option_resume != ResumeOptions() and option_resume != resume:
            raise RunRequestError(
                "RunRequest.resume conflicts with RunRequest.options.resume"
            )
        data["resume"] = resume.to_dict()

    return RunOptions.from_dict(data)


def _coerce_run_options(value: RunOptions | Mapping[str, object]) -> RunOptions:
    try:
        return parse_run_options(value)
    except Exception as exc:
        raise RunRequestError(f"RunRequest.options is invalid: {exc}") from exc


def _coerce_resolved_runtime(
    value: ResolvedStageRuntimeOptions | Mapping[str, object] | None,
    *,
    stage_name: str,
) -> ResolvedStageRuntimeOptions:
    if value is None:
        return ResolvedStageRuntimeOptions(stage_id=stage_name)
    if isinstance(value, ResolvedStageRuntimeOptions):
        runtime = value
    elif isinstance(value, Mapping):
        data = dict(value)
        data.setdefault("stage_id", stage_name)
        runtime = ResolvedStageRuntimeOptions(**cast(Any, data))
    else:
        raise RunRequestError(
            "StageExecutionRequest.resolved_runtime must be ResolvedStageRuntimeOptions or mapping"
        )
    if runtime.stage_id != stage_name:
        raise RunRequestError(
            "StageExecutionRequest.resolved_runtime.stage_id must match stage.name"
        )
    return runtime


def _coerce_selectors(value: object) -> PlanSelectors:
    if isinstance(value, PlanSelectors):
        return value
    if isinstance(value, Mapping):
        return PlanSelectors.from_dict(value)
    raise RunRequestError("selectors must be PlanSelectors or mapping")


def _coerce_resume(value: object) -> ResumeOptions:
    if isinstance(value, ResumeOptions):
        return value
    if isinstance(value, Mapping):
        return ResumeOptions.from_dict(value)
    raise RunRequestError("resume must be ResumeOptions or mapping")


def _coerce_fingerprint_context(value: object) -> FingerprintContext:
    if isinstance(value, FingerprintContext):
        return value
    if isinstance(value, Mapping):
        return FingerprintContext.from_dict(value)
    raise RunRequestError("fingerprint_context must be FingerprintContext or mapping")


def _coerce_config_snapshots(value: object) -> ConfigSnapshotInputs:
    if isinstance(value, ConfigSnapshotInputs):
        return value
    if isinstance(value, Mapping):
        return ConfigSnapshotInputs(
            raw=_optional_str(value.get("raw"), "raw"),
            overlays=_optional_str(value.get("overlays"), "overlays"),
            cli_overrides=_optional_str(value.get("cli_overrides"), "cli_overrides"),
        )
    raise RunRequestError("config_snapshots must be ConfigSnapshotInputs or mapping")


def _coerce_provenance_options(value: object) -> ProvenanceCaptureOptions:
    from loom.provenance.models import ProvenanceCaptureOptions

    if isinstance(value, ProvenanceCaptureOptions):
        return value
    raise RunRequestError("provenance_options must be ProvenanceCaptureOptions")


def _default_provenance_options() -> ProvenanceCaptureOptions:
    from loom.provenance.models import ProvenanceCaptureOptions

    return ProvenanceCaptureOptions()


def _is_command_provenance(value: object) -> bool:
    from loom.provenance.models import CommandProvenance

    return isinstance(value, CommandProvenance)


def _coerce_failure_policy(value: object) -> FailurePolicy:
    if isinstance(value, FailurePolicy):
        return value
    if isinstance(value, Mapping):
        raw_stop_on_first_failure = value.get("stop_on_first_failure", True)
        return FailurePolicy(
            stop_on_first_failure=_bool(
                raw_stop_on_first_failure, "failure_policy.stop_on_first_failure"
            )
        )
    raise RunRequestError("failure_policy must be FailurePolicy or mapping")


def _is_composed_config(value: object) -> bool:
    return all(
        hasattr(value, name)
        for name in (
            "resolved",
            "redacted",
            "manifest",
            "provenance",
            "recipe_manifest",
        )
    )


def _plain_mapping(value: Mapping[str, PlainData], path: str) -> dict[str, PlainData]:
    try:
        normalized = ensure_plain_data(dict(value), path=path)
    except PlainDataError as exc:
        raise RunRequestError(f"{path} must be plain-data-compatible: {exc}") from exc
    if not isinstance(normalized, dict):
        raise RunRequestError(f"{path} must be a mapping")
    return cast(dict[str, PlainData], normalized)


def _artifact_ref_mapping(
    value: Mapping[str, ArtifactRef | object], path: str
) -> dict[str, ArtifactRef]:
    if not isinstance(value, Mapping):
        raise RunRequestError(f"{path} must be a mapping")
    output: dict[str, ArtifactRef] = {}
    for key, ref in value.items():
        if not isinstance(key, str) or not key:
            raise RunRequestError(f"{path} keys must be non-empty strings")
        if isinstance(ref, ArtifactRef):
            output[key] = ref
            continue
        try:
            output[key] = ArtifactRef.from_dict(ref)
        except ArtifactValidationError as exc:
            raise RunRequestError(f"{path}[{key!r}] must be ArtifactRef") from exc
    return output


def _coerce_fingerprint_record(
    value: StageFingerprintRecord | Mapping[str, PlainData], path: str
) -> StageFingerprintRecord:
    if isinstance(value, StageFingerprintRecord):
        return value
    try:
        return StageFingerprintRecord.from_dict(value)
    except Exception as exc:
        raise RunRequestError(f"{path} must be StageFingerprintRecord") from exc


def _optional_execution_failure(
    value: ExecutionFailure | Mapping[str, PlainData] | None,
) -> ExecutionFailure | None:
    if value is None:
        return None
    if isinstance(value, ExecutionFailure):
        return value
    if isinstance(value, Mapping):
        return ExecutionFailure.from_dict(value)
    raise RunRequestError("failure must be ExecutionFailure or mapping when set")


def _object_mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RunRequestError(f"{path} must be a mapping")
    return cast(Mapping[str, object], value)


_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "auth",
    "credential",
    "password",
    "secret",
    "token",
)


def redact_executor_metadata(
    metadata: Mapping[str, PlainData] | None,
) -> dict[str, PlainData]:
    """Return executor metadata safe for persisted worker records."""

    return cast(
        dict[str, PlainData],
        _redact_plain_value(dict(metadata or {}), key_path=()),
    )


def _redact_plain_value(value: object, *, key_path: tuple[str, ...]) -> PlainData:
    if key_path and _is_sensitive_key(key_path[-1]):
        return "[redacted]"
    if isinstance(value, Mapping):
        if key_path and key_path[-1].lower() in {"env", "environment"}:
            return {
                "key_count": len(value),
                "keys": cast(list[PlainData], sorted(str(key) for key in value)),
            }
        output: dict[str, PlainData] = {}
        for key, item in value.items():
            key_text = str(key)
            output[key_text] = _redact_plain_value(
                item,
                key_path=(*key_path, key_text),
            )
        return output
    if isinstance(value, Sequence) and not isinstance(value, (bytes, str)):
        redacted_items: list[PlainData] = []
        for item in value:
            if isinstance(item, str) and _looks_like_secret_argument(item):
                redacted_items.append("[redacted]")
            else:
                redacted_items.append(_redact_plain_value(item, key_path=key_path))
        return redacted_items
    try:
        return ensure_plain_data(value, path="executor_metadata")
    except PlainDataError as exc:
        raise RunRequestError(
            f"executor_metadata must be plain-data-compatible: {exc}"
        ) from exc


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _looks_like_secret_argument(value: str) -> bool:
    lowered = value.lower().replace("-", "_")
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS) and "=" in value


def _reason_tuple(value: tuple[PlanReason, ...]) -> tuple[PlanReason, ...]:
    if not isinstance(value, tuple):
        raise RunRequestError("reasons must be a tuple")
    for item in value:
        if not isinstance(item, PlanReason):
            raise RunRequestError("reasons entries must be PlanReason")
    return value


def _stage_status(value: StageStatus | str) -> StageStatus:
    try:
        return value if isinstance(value, StageStatus) else StageStatus(value)
    except ValueError as exc:
        raise RunRequestError(f"invalid stage status: {value!r}") from exc


def _run_status(value: RunStatus | str) -> RunStatus:
    try:
        return value if isinstance(value, RunStatus) else RunStatus(value)
    except ValueError as exc:
        raise RunRequestError(f"invalid run status: {value!r}") from exc


def _plan_action(value: PlanAction | str) -> PlanAction:
    try:
        return value if isinstance(value, PlanAction) else PlanAction(value)
    except ValueError as exc:
        raise RunRequestError(f"invalid plan action: {value!r}") from exc


def _str(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise RunRequestError(f"{field_name} must be a non-empty string")
    return value


def _optional_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RunRequestError(f"{field_name} must be a string when set")
    return value


def _int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise RunRequestError(f"{field_name} must be an integer")
    return value


def _optional_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _int(value, field_name)


def _bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise RunRequestError(f"{field_name} must be a bool")
    return value


__all__ = [
    "EXECUTION_FAILURE_SCHEMA_VERSION",
    "STAGE_WORKER_REQUEST_SCHEMA_VERSION",
    "STAGE_WORKER_RESULT_SCHEMA_VERSION",
    "ConfigSnapshotInputs",
    "ExecutionFailure",
    "FailurePolicy",
    "RunRequest",
    "RunResult",
    "StageExecutionRequest",
    "StageExecutionResult",
    "StageRunResult",
    "StageWorkerRequest",
    "StageWorkerResult",
    "redact_executor_metadata",
]
