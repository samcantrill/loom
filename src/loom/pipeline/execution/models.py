"""Execution data models for the local pipeline runtime."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

from loom.artifacts import ArtifactRef
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
from loom.pipeline.specs import PipelineSpec, StageSpec
from loom.pipeline.stage import Stage
from loom.pipeline.status import RunStatus, StageStatus
from loom.serialization import PlainData, ensure_plain_data, load_versioned_document
from loom.serialization.errors import PlainDataError
from loom.serialization.errors import SchemaVersionError
from loom.timestamps import safe_timestamp_for_path

from .errors import RunRequestError

if TYPE_CHECKING:
    from loom.config.api import ComposedConfig
    from loom.provenance.models import CommandProvenance, ProvenanceCaptureOptions

EXECUTION_FAILURE_SCHEMA_VERSION = 1

_VALID_FAILURE_TYPES = {
    "stage_exception",
    "stage_contract",
    "output_validation",
    "target_construction",
    "plan_execution",
    "store_commit",
    "executor_infrastructure",
}


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
        if not self.stop_on_first_failure:
            raise RunRequestError("continue-on-failure is deferred beyond Phase 9")


@dataclass(frozen=True, slots=True)
class RunRequest:
    config: ComposedConfig | Mapping[str, PlainData] | None = None
    pipeline: PipelineSpec | None = None
    run_id: str | None = None
    open_existing: bool = False
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

        object.__setattr__(self, "selectors", _coerce_selectors(self.selectors))
        object.__setattr__(self, "resume", _coerce_resume(self.resume))
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
        if self.run_id is None:
            object.__setattr__(
                self, "run_id", safe_timestamp_for_path(timespec="seconds")
            )
        if not isinstance(self.run_id, str) or not self.run_id:
            raise RunRequestError("RunRequest.run_id must be a non-empty string")
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))


@dataclass(frozen=True, slots=True)
class ExecutionFailure:
    schema_version: int
    run_id: str
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
    executor_metadata: Mapping[str, PlainData] = field(default_factory=dict)
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != EXECUTION_FAILURE_SCHEMA_VERSION:
            raise RunRequestError("ExecutionFailure.schema_version must be 1")
        if not isinstance(self.run_id, str) or not self.run_id:
            raise RunRequestError("ExecutionFailure.run_id must be a non-empty string")
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
        object.__setattr__(
            self,
            "executor_metadata",
            _plain_mapping(self.executor_metadata, "executor_metadata"),
        )
        object.__setattr__(self, "details", _plain_mapping(self.details, "details"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
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
                    "run_id",
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
                    "executor_metadata",
                    "details",
                },
            )
        except SchemaVersionError as exc:
            raise RunRequestError(f"ExecutionFailure.from_dict: {exc}") from exc

        return cls(
            schema_version=_int(mapping["schema_version"], "schema_version"),
            run_id=_str(mapping["run_id"], "run_id"),
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
            executor_metadata=_plain_mapping(
                cast(Mapping[str, PlainData], mapping.get("executor_metadata", {})),
                "executor_metadata",
            ),
            details=_plain_mapping(
                cast(Mapping[str, PlainData], mapping.get("details", {})), "details"
            ),
        )


@dataclass(frozen=True, slots=True)
class StageExecutionRequest:
    run_id: str
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

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id:
            raise RunRequestError(
                "StageExecutionRequest.run_id must be a non-empty string"
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
        if self.status not in {StageStatus.SUCCEEDED, StageStatus.FAILED}:
            raise RunRequestError(
                "StageExecutionResult.status must be SUCCEEDED or FAILED"
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
    run_id: str
    run_dir: Path
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
        if not isinstance(self.run_id, str) or not self.run_id:
            raise RunRequestError("RunResult.run_id must be a non-empty string")
        object.__setattr__(self, "run_dir", Path(self.run_dir))
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
        for name in ("resolved", "redacted", "provenance", "recipe_manifest")
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
    value: Mapping[str, ArtifactRef], path: str
) -> dict[str, ArtifactRef]:
    if not isinstance(value, Mapping):
        raise RunRequestError(f"{path} must be a mapping")
    output: dict[str, ArtifactRef] = {}
    for key, ref in value.items():
        if not isinstance(key, str) or not key:
            raise RunRequestError(f"{path} keys must be non-empty strings")
        if not isinstance(ref, ArtifactRef):
            raise RunRequestError(f"{path}[{key!r}] must be ArtifactRef")
        output[key] = ref
    return output


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
    "ConfigSnapshotInputs",
    "ExecutionFailure",
    "FailurePolicy",
    "RunRequest",
    "RunResult",
    "StageExecutionRequest",
    "StageExecutionResult",
    "StageRunResult",
]
