"""Execution data models for the local pipeline runtime."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast

from loom._validation import require_schema_version
from loom.artifacts import ArtifactRef, ArtifactValidationError
from loom.pipeline.context import StageContext
from loom.pipeline.errors import RuntimeResourceError
from loom.pipeline.planning import (
    PlanAction,
    PlanReason,
    StageFingerprintRecord,
    StagePlan,
)
from loom.pipeline.runtime import (
    ResolvedStageRuntimeOptions,
)
from loom.pipeline.specs import StageSpec
from loom.pipeline.stage import Stage
from loom.pipeline.status import StageStatus
from loom.serialization import (
    PlainData,
    ensure_plain_data,
    freeze_plain_data,
    load_versioned_document,
    thaw_plain_data,
)
from loom.serialization.errors import PlainDataError
from loom.serialization.errors import SchemaVersionError
from .errors import RunRequestError

if TYPE_CHECKING:
    pass

EXECUTION_FAILURE_SCHEMA_VERSION = 1
STAGE_WORKER_REQUEST_SCHEMA_VERSION = 2
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
_PLUGIN_ACTIVATIONS_METADATA_KEY = "plugin_activations"


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
        require_schema_version(
            self.schema_version,
            field="ExecutionFailure.schema_version",
            current=EXECUTION_FAILURE_SCHEMA_VERSION,
            error_type=RunRequestError,
        )
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
            "executor_metadata": thaw_plain_data(
                self.executor_metadata, path="executor_metadata"
            ),
            "details": thaw_plain_data(self.details, path="details"),
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
        require_schema_version(
            self.schema_version,
            field="StageWorkerRequest.schema_version",
            current=STAGE_WORKER_REQUEST_SCHEMA_VERSION,
            error_type=RunRequestError,
        )
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
        metadata = _plain_mapping(self.metadata, "metadata")
        _validate_worker_resource_selection(runtime, metadata)
        object.__setattr__(self, "resolved_runtime", runtime)
        object.__setattr__(
            self,
            "executor_metadata",
            _plain_mapping(self.executor_metadata, "executor_metadata"),
        )
        object.__setattr__(self, "metadata", metadata)

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
            "resolved_runtime": thaw_plain_data(
                self.resolved_runtime, path="resolved_runtime"
            ),
            "executor_metadata": thaw_plain_data(
                self.executor_metadata, path="executor_metadata"
            ),
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
        }

    def to_safe_metadata(self) -> dict[str, PlainData]:
        """Describe this request without private paths, payloads or credentials.

        This is an observation view, not an execution handoff or identity input.
        Logical input names and requested resources remain visible; the existing
        ``to_dict`` method alone retains the complete private request.
        """
        return redact_executor_metadata(
            {
                "run_uri": self.run_uri,
                "stage_name": self.stage_name,
                "attempt": self.attempt,
                "prepared_at": self.prepared_at,
                "executor_name": self.executor_name,
                "inputs": cast(list[PlainData], sorted(self.inputs)),
                "resolved_runtime": dict(self.resolved_runtime),
                "stdout_path": self.stdout_path,
                "stderr_path": self.stderr_path,
                "traceback_path": self.traceback_path,
                "result_path": self.result_path,
                "executor_metadata": dict(self.executor_metadata),
            },
            public=True,
        )

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
            raise RunRequestError(
                f"StageWorkerRequest.from_dict: {exc}; finish or cancel the saved "
                "work in its pinned environment and prepare a fresh identity"
            ) from exc
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


def _validate_worker_resource_selection(
    runtime: Mapping[str, PlainData], metadata: Mapping[str, PlainData]
) -> None:
    """Reject a retained worker whose saved post-demand projection changed."""

    selection = runtime.get("resource_selection")
    if selection is None:
        raise RunRequestError(
            "StageWorkerRequest.resolved_runtime must include resource_selection"
        )
    resources = runtime.get("resources")
    policy = runtime.get("resource_policy")
    if not isinstance(resources, Mapping) or not isinstance(policy, Mapping):
        raise RunRequestError(
            "StageWorkerRequest resource selection requires resolved runtime policy and resources"
        )
    entries = resources.get("entries")
    if not isinstance(entries, Mapping):
        raise RunRequestError(
            "StageWorkerRequest resolved runtime resources are invalid"
        )
    from loom.pipeline.runtime.resource_policy import (
        ResourcePolicy,
        validate_resource_selection,
    )

    try:
        actual = validate_resource_selection(
            selection,
            entries,
            ResourcePolicy.from_dict(policy),
            path="StageWorkerRequest.resolved_runtime.resource_selection",
        )
    except RuntimeResourceError as exc:
        raise RunRequestError(str(exc)) from exc
    legacy = metadata.get("resource_selection")
    if legacy is not None and legacy != {
        key: list(value) for key, value in actual.items()
    }:
        raise RunRequestError(
            "StageWorkerRequest metadata resource selection conflicts with resolved runtime"
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
        require_schema_version(
            self.schema_version,
            field="StageWorkerResult.schema_version",
            current=STAGE_WORKER_RESULT_SCHEMA_VERSION,
            error_type=RunRequestError,
        )
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
            raise RunRequestError(
                "StageWorkerResult.failure must be null for CANCELLED"
            )
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
            "executor_metadata": thaw_plain_data(
                self.executor_metadata, path="executor_metadata"
            ),
        }

    def to_safe_metadata(self) -> dict[str, PlainData]:
        """Return route/outcome facts without private logs or artifact payloads."""
        return _execution_result_safe_metadata(self)

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
    worker_authority_cli_args: tuple[str, ...] = ()

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
        if not isinstance(self.worker_authority_cli_args, tuple) or not all(
            isinstance(argument, str) and argument
            for argument in self.worker_authority_cli_args
        ):
            raise RunRequestError(
                "StageExecutionRequest.worker_authority_cli_args must be a tuple of non-empty strings"
            )
        object.__setattr__(
            self,
            "resolved_runtime",
            _coerce_resolved_runtime(self.resolved_runtime, stage_name=self.stage.name),
        )

    def to_safe_metadata(self) -> dict[str, PlainData]:
        """Describe the admitted request before invoking opaque stage code.

        Resource demand and selection are requested/reserved facts, not measured
        device visibility. Workspace/log locations are opaque in this public
        view, while input names remain logical graph identities.
        """
        runtime = cast(ResolvedStageRuntimeOptions, self.resolved_runtime)
        return redact_executor_metadata(
            {
                "run_uri": self.run_uri,
                "stage_name": self.stage.name,
                "attempt": self.attempt,
                "executor_name": runtime.executor,
                "resolved_runtime": runtime.to_safe_metadata(),
                "inputs": cast(list[PlainData], sorted(self.inputs)),
                "workspace": None
                if self.context._local_workspace_dir is None
                else str(self.context._local_workspace_dir),
                "output_dir": None
                if self.context._local_output_dir is None
                else str(self.context._local_output_dir),
                "stdout_path": str(self.stdout_path),
                "stderr_path": str(self.stderr_path),
                "traceback_path": str(self.traceback_path),
            },
            public=True,
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
            raise RunRequestError(
                "StageExecutionResult CANCELLED must not include outputs"
            )
        for name in ("stdout_path", "stderr_path", "traceback_path"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise RunRequestError(
                    f"StageExecutionResult.{name} must be a string when set"
                )
        object.__setattr__(self, "outputs", MappingProxyType(dict(self.outputs)))
        object.__setattr__(
            self,
            "executor_metadata",
            _plain_mapping(self.executor_metadata, "executor_metadata"),
        )

    def to_safe_metadata(self) -> dict[str, PlainData]:
        """Return the existing execution outcome and redacted route metadata."""
        return _execution_result_safe_metadata(self)


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

    def to_safe_metadata(self) -> dict[str, PlainData]:
        """Return the existing execution outcome and redacted route metadata."""
        return _execution_result_safe_metadata(self)


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


def _plain_mapping(
    value: Mapping[str, PlainData], path: str
) -> Mapping[str, PlainData]:
    try:
        normalized = freeze_plain_data(value, path=path)
    except PlainDataError as exc:
        raise RunRequestError(f"{path} must be plain-data-compatible: {exc}") from exc
    if not isinstance(normalized, Mapping):
        raise RunRequestError(f"{path} must be a mapping")
    return cast(Mapping[str, PlainData], normalized)


def _artifact_ref_mapping(
    value: Mapping[str, ArtifactRef | object], path: str
) -> Mapping[str, ArtifactRef]:
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
    return MappingProxyType(output)


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
    *,
    public: bool = False,
) -> dict[str, PlainData]:
    """Redact execution metadata for private storage or public observation.

    The default preserves the existing private worker-record shape. ``public``
    additionally hides host paths, raw process output, arbitrary exception text,
    URI credentials and resource-attribute values. Neither view is an execution
    input or a replacement for a private request. Typed outcome codes, argument
    switches, mount access modes and requested/observed numeric facts survive.
    """

    return cast(
        dict[str, PlainData],
        _redact_plain_value(dict(metadata or {}), key_path=(), public=public),
    )


def _redact_plain_value(
    value: object, *, key_path: tuple[str, ...], public: bool = False
) -> PlainData:
    if (
        public
        and key_path
        and key_path[-1].lower()
        in {
            "stdout",
            "stderr",
            "traceback",
            "traceback_text",
            "message",
            "launch_error",
            "error",
            "setup_error",
            "script_text",
            "script",
        }
    ):
        return None if value is None else "[redacted]"
    if (
        public
        and key_path
        and key_path[-1].lower() == "attributes"
        and isinstance(value, Mapping)
    ):
        return "[redacted]"
    if key_path and _is_sensitive_key(key_path[-1]):
        return "[redacted]"
    if isinstance(value, Mapping):
        if key_path and key_path[-1].lower() in {"env", "environment"}:
            if public and set(value) == {"key_count", "keys"}:
                return {
                    "key_count": cast(int, value["key_count"]),
                    "keys": list(value["keys"]),
                }
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
                public=public,
            )
        return output
    if isinstance(value, Sequence) and not isinstance(value, (bytes, str)):
        redacted_items: list[PlainData] = []
        previous_argument = ""
        for item in value:
            if public and (
                previous_argument == "-c"
                or (
                    previous_argument.startswith("--")
                    and "=" not in previous_argument
                    and _is_sensitive_key(previous_argument)
                )
            ):
                redacted_items.append("[redacted]")
            elif (
                not public
                and isinstance(item, str)
                and _looks_like_secret_argument(item)
            ):
                redacted_items.append("[redacted]")
            else:
                redacted_items.append(
                    _redact_plain_value(item, key_path=key_path, public=public)
                )
            previous_argument = item if isinstance(item, str) else ""
        return redacted_items
    if public and isinstance(value, str):
        return _public_execution_string(value)
    try:
        return ensure_plain_data(value, path="executor_metadata")
    except PlainDataError as exc:
        raise RunRequestError(
            f"executor_metadata must be plain-data-compatible: {exc}"
        ) from exc


def _public_execution_string(value: str) -> str:
    if value.startswith("file:"):
        return "[redacted-path]"
    if "://" in value:
        try:
            uri = urlsplit(value)
            authority = uri.netloc.rsplit("@", 1)[-1]
            return urlunsplit((uri.scheme, authority, uri.path, "", ""))
        except ValueError:
            return "[redacted]"
    if _looks_like_secret_argument(value):
        return "[redacted]"
    if re.search(r"(?:^|[=:\s])/", value):
        if value.startswith("--") and "=" in value:
            return value.split("=", 1)[0] + "=[redacted-path]"
        return "[redacted-path]"
    return value


def _execution_result_safe_metadata(
    result: StageExecutionResult | StageWorkerResult | StageRunResult,
) -> dict[str, PlainData]:
    failure = cast(ExecutionFailure | None, result.failure)
    metadata: dict[str, PlainData] = {
        "stage_name": result.stage_name,
        "attempt": result.attempt,
        "status": None if result.status is None else result.status.value,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "outputs": cast(list[PlainData], sorted(result.outputs)),
        "failure": None
        if failure is None
        else {
            "executor": failure.executor,
            "failure_type": failure.failure_type,
            "exception_type": failure.exception_type,
            "exit_code": failure.exit_code,
            "signal": failure.signal,
        },
        "executor_metadata": dict(result.executor_metadata),
    }
    for name in (
        "executor_name",
        "run_uri",
        "stdout_path",
        "stderr_path",
        "traceback_path",
        "exit_code",
        "signal",
    ):
        if hasattr(result, name):
            metadata[name] = getattr(result, name)
    return redact_executor_metadata(metadata, public=True)


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
    "ExecutionFailure",
    "StageExecutionRequest",
    "StageExecutionResult",
    "StageRunResult",
    "StageWorkerRequest",
    "StageWorkerResult",
    "redact_executor_metadata",
]
