"""Planning data models and deterministic plain-data serialization."""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from loom import __version__ as _LOOM_VERSION
from loom.artifacts import ArtifactRef, ArtifactValidationError
from loom.serialization import PlainData, ensure_plain_data
from loom.serialization.errors import PlainDataError

from .errors import PlanSerializationError, PlanningValidationError

PLAN_SCHEMA_VERSION = 1
STAGE_FINGERPRINT_SCHEMA_VERSION = 2
STAGE_FINGERPRINT_POLICY_NAME = "loom.stage.semantic"
STAGE_FINGERPRINT_POLICY_VERSION = 2
DEFAULT_FINGERPRINT_ALGORITHM = "sha256"


class PlanAction(StrEnum):
    RUN = "RUN"
    REUSE = "REUSE"
    SKIP = "SKIP"
    STALE = "STALE"
    BLOCKED = "BLOCKED"


class FingerprintStatus(StrEnum):
    COMPUTED = "COMPUTED"
    PENDING_INPUTS = "PENDING_INPUTS"


class PlanReasonCode(StrEnum):
    RESUME_DISABLED = "RESUME_DISABLED"
    NO_PRIOR_STATUS = "NO_PRIOR_STATUS"
    PRIOR_STATUS_NOT_SUCCEEDED = "PRIOR_STATUS_NOT_SUCCEEDED"
    PRIOR_STATUS_RUNNING = "PRIOR_STATUS_RUNNING"
    MISSING_FINGERPRINT = "MISSING_FINGERPRINT"
    MISSING_INPUTS = "MISSING_INPUTS"
    MISSING_OUTPUTS = "MISSING_OUTPUTS"
    MISSING_OUTPUT_REF = "MISSING_OUTPUT_REF"
    OUTPUT_SPEC_MISMATCH = "OUTPUT_SPEC_MISMATCH"
    FINGERPRINT_MATCH = "FINGERPRINT_MATCH"
    FINGERPRINT_CHANGED = "FINGERPRINT_CHANGED"
    FINGERPRINT_POLICY_CHANGED = "FINGERPRINT_POLICY_CHANGED"
    ARTIFACT_VALIDATED = "ARTIFACT_VALIDATED"
    ARTIFACT_MISSING = "ARTIFACT_MISSING"
    ARTIFACT_CHECKSUM_MISMATCH = "ARTIFACT_CHECKSUM_MISMATCH"
    ARTIFACT_VALIDATION_FAILED = "ARTIFACT_VALIDATION_FAILED"
    ARTIFACT_INDEX_CONFLICT = "ARTIFACT_INDEX_CONFLICT"
    FORCED_BY_SELECTOR = "FORCED_BY_SELECTOR"
    FROM_STAGE_SELECTED = "FROM_STAGE_SELECTED"
    ONLY_STAGE_SELECTED = "ONLY_STAGE_SELECTED"
    OUTSIDE_ONLY_SELECTION = "OUTSIDE_ONLY_SELECTION"
    SKIPPED_BY_SELECTOR = "SKIPPED_BY_SELECTOR"
    BLOCKED_BY_UPSTREAM = "BLOCKED_BY_UPSTREAM"
    UPSTREAM_WILL_RUN = "UPSTREAM_WILL_RUN"
    UPSTREAM_SKIPPED = "UPSTREAM_SKIPPED"
    UPSTREAM_BLOCKED = "UPSTREAM_BLOCKED"
    UPSTREAM_STALE = "UPSTREAM_STALE"
    UNAVAILABLE_UPSTREAM_INPUT = "UNAVAILABLE_UPSTREAM_INPUT"
    PENDING_UPSTREAM_INPUT = "PENDING_UPSTREAM_INPUT"


@dataclass(frozen=True, slots=True)
class PlanReason:
    code: PlanReasonCode
    message: str
    stage_name: str | None = None
    upstream_stage: str | None = None
    input_name: str | None = None
    output_name: str | None = None
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", coerce_reason_code(self.code))
        object.__setattr__(self, "message", require_str(self.message, "message"))
        object.__setattr__(
            self, "stage_name", optional_str(self.stage_name, "stage_name")
        )
        object.__setattr__(
            self, "upstream_stage", optional_str(self.upstream_stage, "upstream_stage")
        )
        object.__setattr__(
            self, "input_name", optional_str(self.input_name, "input_name")
        )
        object.__setattr__(
            self, "output_name", optional_str(self.output_name, "output_name")
        )
        object.__setattr__(self, "details", plain_mapping(self.details, "details"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "code": self.code.value,
            "message": self.message,
            "stage_name": self.stage_name,
            "upstream_stage": self.upstream_stage,
            "input_name": self.input_name,
            "output_name": self.output_name,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, data: object) -> "PlanReason":
        mapping = require_mapping(data, "PlanReason")
        reject_unknown(
            mapping,
            {
                "code",
                "message",
                "stage_name",
                "upstream_stage",
                "input_name",
                "output_name",
                "details",
            },
            "PlanReason",
        )
        require_fields(mapping, {"code", "message"}, "PlanReason")
        return cls(
            code=coerce_reason_code(mapping["code"]),
            message=require_str(mapping["message"], "message"),
            stage_name=optional_str(mapping.get("stage_name"), "stage_name"),
            upstream_stage=optional_str(
                mapping.get("upstream_stage"), "upstream_stage"
            ),
            input_name=optional_str(mapping.get("input_name"), "input_name"),
            output_name=optional_str(mapping.get("output_name"), "output_name"),
            details=plain_mapping(mapping.get("details", {}), "details"),
        )


@dataclass(frozen=True, slots=True)
class PlanSelectors:
    force_stages: tuple[str, ...] = ()
    from_stage: str | None = None
    only_stages: tuple[str, ...] = ()
    skip_stages: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "force_stages", str_tuple(self.force_stages, "force_stages")
        )
        object.__setattr__(
            self, "from_stage", optional_str(self.from_stage, "from_stage")
        )
        object.__setattr__(
            self, "only_stages", str_tuple(self.only_stages, "only_stages")
        )
        object.__setattr__(
            self, "skip_stages", str_tuple(self.skip_stages, "skip_stages")
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "force_stages": list(self.force_stages),
            "from_stage": self.from_stage,
            "only_stages": list(self.only_stages),
            "skip_stages": list(self.skip_stages),
        }

    @classmethod
    def from_dict(cls, data: object) -> "PlanSelectors":
        mapping = require_mapping(data, "PlanSelectors")
        reject_unknown(
            mapping,
            {"force_stages", "from_stage", "only_stages", "skip_stages"},
            "PlanSelectors",
        )
        return cls(
            force_stages=str_tuple(mapping.get("force_stages", ()), "force_stages"),
            from_stage=optional_str(mapping.get("from_stage"), "from_stage"),
            only_stages=str_tuple(mapping.get("only_stages", ()), "only_stages"),
            skip_stages=str_tuple(mapping.get("skip_stages", ()), "skip_stages"),
        )


@dataclass(frozen=True, slots=True)
class ResumeOptions:
    enabled: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise PlanningValidationError("ResumeOptions.enabled must be a bool")

    def to_dict(self) -> dict[str, PlainData]:
        return {"enabled": self.enabled}

    @classmethod
    def from_dict(cls, data: object) -> "ResumeOptions":
        mapping = require_mapping(data, "ResumeOptions")
        reject_unknown(mapping, {"enabled"}, "ResumeOptions")
        return cls(enabled=require_bool(mapping.get("enabled", True), "enabled"))


@dataclass(frozen=True, slots=True)
class FingerprintContext:
    python_version: str | None = None
    loom_version: str | None = None
    git: Mapping[str, PlainData] = field(default_factory=dict)
    dependencies: Mapping[str, str] = field(default_factory=dict)
    extra: Mapping[str, PlainData] = field(default_factory=dict)
    algorithm: str = DEFAULT_FINGERPRINT_ALGORITHM
    policy_name: str = STAGE_FINGERPRINT_POLICY_NAME
    policy_version: int = STAGE_FINGERPRINT_POLICY_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "python_version", optional_str(self.python_version, "python_version")
        )
        object.__setattr__(
            self, "loom_version", optional_str(self.loom_version, "loom_version")
        )
        object.__setattr__(self, "git", plain_mapping(self.git, "git"))
        object.__setattr__(
            self, "dependencies", str_mapping(self.dependencies, "dependencies")
        )
        object.__setattr__(self, "extra", plain_mapping(self.extra, "extra"))
        object.__setattr__(self, "algorithm", require_str(self.algorithm, "algorithm"))
        object.__setattr__(
            self, "policy_name", require_str(self.policy_name, "policy_name")
        )
        object.__setattr__(
            self, "policy_version", positive_int(self.policy_version, "policy_version")
        )

    def resolved_python_version(self) -> str:
        return (
            self.python_version
            or f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        )

    def resolved_loom_version(self) -> str:
        return self.loom_version or _LOOM_VERSION

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "python_version": self.resolved_python_version(),
            "loom_version": self.resolved_loom_version(),
            "git": dict(self.git),
            "dependencies": dict(self.dependencies),
            "extra": dict(self.extra),
            "algorithm": self.algorithm,
            "policy_name": self.policy_name,
            "policy_version": self.policy_version,
        }

    @classmethod
    def from_dict(cls, data: object) -> "FingerprintContext":
        mapping = require_mapping(data, "FingerprintContext")
        reject_unknown(
            mapping,
            {
                "python_version",
                "loom_version",
                "git",
                "dependencies",
                "extra",
                "algorithm",
                "policy_name",
                "policy_version",
            },
            "FingerprintContext",
        )
        return cls(
            python_version=optional_str(
                mapping.get("python_version"), "python_version"
            ),
            loom_version=optional_str(mapping.get("loom_version"), "loom_version"),
            git=plain_mapping(mapping.get("git", {}), "git"),
            dependencies=str_mapping(mapping.get("dependencies", {}), "dependencies"),
            extra=plain_mapping(mapping.get("extra", {}), "extra"),
            algorithm=require_str(
                mapping.get("algorithm", DEFAULT_FINGERPRINT_ALGORITHM), "algorithm"
            ),
            policy_name=require_str(
                mapping.get("policy_name", STAGE_FINGERPRINT_POLICY_NAME), "policy_name"
            ),
            policy_version=positive_int(
                mapping.get("policy_version", STAGE_FINGERPRINT_POLICY_VERSION),
                "policy_version",
            ),
        )


@dataclass(frozen=True, slots=True)
class BoundInput:
    input_name: str
    source_stage: str
    source_output: str
    artifact_ref: ArtifactRef

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "input_name", require_str(self.input_name, "input_name")
        )
        object.__setattr__(
            self, "source_stage", require_str(self.source_stage, "source_stage")
        )
        object.__setattr__(
            self, "source_output", require_str(self.source_output, "source_output")
        )
        object.__setattr__(
            self, "artifact_ref", artifact_ref(self.artifact_ref, "artifact_ref")
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "input_name": self.input_name,
            "source_stage": self.source_stage,
            "source_output": self.source_output,
            "artifact_ref": self.artifact_ref.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: object) -> "BoundInput":
        mapping = require_mapping(data, "BoundInput")
        reject_unknown(
            mapping,
            {"input_name", "source_stage", "source_output", "artifact_ref"},
            "BoundInput",
        )
        require_fields(
            mapping,
            {"input_name", "source_stage", "source_output", "artifact_ref"},
            "BoundInput",
        )
        return cls(
            input_name=require_str(mapping["input_name"], "input_name"),
            source_stage=require_str(mapping["source_stage"], "source_stage"),
            source_output=require_str(mapping["source_output"], "source_output"),
            artifact_ref=artifact_ref(mapping["artifact_ref"], "artifact_ref"),
        )


@dataclass(frozen=True, slots=True)
class PendingInput:
    input_name: str
    source_stage: str
    source_output: str
    reason: PlanReason

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "input_name", require_str(self.input_name, "input_name")
        )
        object.__setattr__(
            self, "source_stage", require_str(self.source_stage, "source_stage")
        )
        object.__setattr__(
            self, "source_output", require_str(self.source_output, "source_output")
        )
        object.__setattr__(self, "reason", plan_reason(self.reason, "reason"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "input_name": self.input_name,
            "source_stage": self.source_stage,
            "source_output": self.source_output,
            "reason": self.reason.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: object) -> "PendingInput":
        mapping = require_mapping(data, "PendingInput")
        reject_unknown(
            mapping,
            {"input_name", "source_stage", "source_output", "reason"},
            "PendingInput",
        )
        require_fields(
            mapping,
            {"input_name", "source_stage", "source_output", "reason"},
            "PendingInput",
        )
        return cls(
            input_name=require_str(mapping["input_name"], "input_name"),
            source_stage=require_str(mapping["source_stage"], "source_stage"),
            source_output=require_str(mapping["source_output"], "source_output"),
            reason=plan_reason(mapping["reason"], "reason"),
        )


@dataclass(frozen=True, slots=True)
class StageFingerprintPayload:
    schema_version: int
    policy_name: str
    policy_version: int
    stage_name: str
    factory_target: str
    factory_init: Mapping[str, PlainData]
    stage_config: Mapping[str, PlainData]
    fingerprint_fields: Mapping[str, PlainData]
    declared_inputs: Mapping[str, str]
    bound_inputs: Mapping[str, Mapping[str, PlainData]]
    declared_outputs: Mapping[str, Mapping[str, PlainData]]
    python_version: str
    loom_version: str
    git: Mapping[str, PlainData]
    dependencies: Mapping[str, str]
    extra: Mapping[str, PlainData]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "schema_version", positive_int(self.schema_version, "schema_version")
        )
        object.__setattr__(
            self, "policy_name", require_str(self.policy_name, "policy_name")
        )
        object.__setattr__(
            self, "policy_version", positive_int(self.policy_version, "policy_version")
        )
        object.__setattr__(
            self, "stage_name", require_str(self.stage_name, "stage_name")
        )
        object.__setattr__(
            self,
            "factory_target",
            require_str(self.factory_target, "factory_target"),
        )
        object.__setattr__(
            self, "factory_init", plain_mapping(self.factory_init, "factory_init")
        )
        object.__setattr__(
            self, "stage_config", plain_mapping(self.stage_config, "stage_config")
        )
        object.__setattr__(
            self,
            "fingerprint_fields",
            plain_mapping(self.fingerprint_fields, "fingerprint_fields"),
        )
        object.__setattr__(
            self,
            "declared_inputs",
            str_mapping(self.declared_inputs, "declared_inputs"),
        )
        object.__setattr__(
            self,
            "bound_inputs",
            nested_plain_mapping(self.bound_inputs, "bound_inputs"),
        )
        object.__setattr__(
            self,
            "declared_outputs",
            nested_plain_mapping(self.declared_outputs, "declared_outputs"),
        )
        object.__setattr__(
            self, "python_version", require_str(self.python_version, "python_version")
        )
        object.__setattr__(
            self, "loom_version", require_str(self.loom_version, "loom_version")
        )
        object.__setattr__(self, "git", plain_mapping(self.git, "git"))
        object.__setattr__(
            self, "dependencies", str_mapping(self.dependencies, "dependencies")
        )
        object.__setattr__(self, "extra", plain_mapping(self.extra, "extra"))

    def to_hash_input(self) -> dict[str, PlainData]:
        return self.to_dict()

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "policy_name": self.policy_name,
            "policy_version": self.policy_version,
            "stage_name": self.stage_name,
            "factory_target": self.factory_target,
            "factory_init": dict(self.factory_init),
            "stage_config": dict(self.stage_config),
            "fingerprint_fields": dict(self.fingerprint_fields),
            "declared_inputs": dict(self.declared_inputs),
            "bound_inputs": {
                key: dict(value) for key, value in self.bound_inputs.items()
            },
            "declared_outputs": {
                key: dict(value) for key, value in self.declared_outputs.items()
            },
            "python_version": self.python_version,
            "loom_version": self.loom_version,
            "git": dict(self.git),
            "dependencies": dict(self.dependencies),
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, data: object) -> "StageFingerprintPayload":
        mapping = require_mapping(data, "StageFingerprintPayload")
        allowed = {
            "schema_version",
            "policy_name",
            "policy_version",
            "stage_name",
            "factory_target",
            "factory_init",
            "stage_config",
            "fingerprint_fields",
            "declared_inputs",
            "bound_inputs",
            "declared_outputs",
            "python_version",
            "loom_version",
            "git",
            "dependencies",
            "extra",
            "target_path",
        }
        reject_unknown(mapping, allowed, "StageFingerprintPayload")
        required = {
            "schema_version",
            "policy_name",
            "policy_version",
            "stage_name",
            "stage_config",
            "declared_inputs",
            "bound_inputs",
            "declared_outputs",
            "python_version",
            "loom_version",
            "git",
            "dependencies",
            "extra",
        }
        require_fields(mapping, required, "StageFingerprintPayload")
        factory_target = mapping.get("factory_target")
        if factory_target is None:
            factory_target = mapping.get("target_path")
        if factory_target is None:
            raise PlanSerializationError(
                "StageFingerprintPayload must include factory_target or target_path"
            )
        return cls(
            schema_version=positive_int(mapping["schema_version"], "schema_version"),
            policy_name=require_str(mapping["policy_name"], "policy_name"),
            policy_version=positive_int(mapping["policy_version"], "policy_version"),
            stage_name=require_str(mapping["stage_name"], "stage_name"),
            factory_target=require_str(factory_target, "factory_target"),
            factory_init=plain_mapping(mapping.get("factory_init", {}), "factory_init"),
            stage_config=plain_mapping(mapping["stage_config"], "stage_config"),
            fingerprint_fields=plain_mapping(
                mapping.get("fingerprint_fields", {}), "fingerprint_fields"
            ),
            declared_inputs=str_mapping(mapping["declared_inputs"], "declared_inputs"),
            bound_inputs=nested_plain_mapping(mapping["bound_inputs"], "bound_inputs"),
            declared_outputs=nested_plain_mapping(
                mapping["declared_outputs"], "declared_outputs"
            ),
            python_version=require_str(mapping["python_version"], "python_version"),
            loom_version=require_str(mapping["loom_version"], "loom_version"),
            git=plain_mapping(mapping["git"], "git"),
            dependencies=str_mapping(mapping["dependencies"], "dependencies"),
            extra=plain_mapping(mapping["extra"], "extra"),
        )


@dataclass(frozen=True, slots=True)
class StageFingerprintRecord:
    schema_version: int
    algorithm: str
    policy_name: str
    policy_version: int
    fingerprint: str
    payload: StageFingerprintPayload
    inputs_summary: Mapping[str, PlainData]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "schema_version", positive_int(self.schema_version, "schema_version")
        )
        object.__setattr__(self, "algorithm", require_str(self.algorithm, "algorithm"))
        object.__setattr__(
            self, "policy_name", require_str(self.policy_name, "policy_name")
        )
        object.__setattr__(
            self, "policy_version", positive_int(self.policy_version, "policy_version")
        )
        object.__setattr__(
            self, "fingerprint", require_str(self.fingerprint, "fingerprint")
        )
        object.__setattr__(
            self, "payload", fingerprint_payload(self.payload, "payload")
        )
        object.__setattr__(
            self, "inputs_summary", plain_mapping(self.inputs_summary, "inputs_summary")
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "algorithm": self.algorithm,
            "policy_name": self.policy_name,
            "policy_version": self.policy_version,
            "fingerprint": self.fingerprint,
            "payload": self.payload.to_dict(),
            "inputs_summary": dict(self.inputs_summary),
        }

    @classmethod
    def from_dict(cls, data: object) -> "StageFingerprintRecord":
        mapping = require_mapping(data, "StageFingerprintRecord")
        allowed = {
            "schema_version",
            "algorithm",
            "policy_name",
            "policy_version",
            "fingerprint",
            "payload",
            "inputs_summary",
        }
        reject_unknown(mapping, allowed, "StageFingerprintRecord")
        require_fields(mapping, allowed, "StageFingerprintRecord")
        return cls(
            schema_version=positive_int(mapping["schema_version"], "schema_version"),
            algorithm=require_str(mapping["algorithm"], "algorithm"),
            policy_name=require_str(mapping["policy_name"], "policy_name"),
            policy_version=positive_int(mapping["policy_version"], "policy_version"),
            fingerprint=require_str(mapping["fingerprint"], "fingerprint"),
            payload=fingerprint_payload(mapping["payload"], "payload"),
            inputs_summary=plain_mapping(mapping["inputs_summary"], "inputs_summary"),
        )


@dataclass(frozen=True, slots=True)
class ResumeCheck:
    stage_name: str
    action: PlanAction
    status: str | None
    attempt: int | None
    prior_fingerprint: StageFingerprintRecord | None
    current_fingerprint: StageFingerprintRecord | None
    inputs: Mapping[str, ArtifactRef]
    outputs: Mapping[str, ArtifactRef]
    reasons: tuple[PlanReason, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "stage_name", require_str(self.stage_name, "stage_name")
        )
        object.__setattr__(self, "action", coerce_plan_action(self.action))
        object.__setattr__(self, "status", optional_str(self.status, "status"))
        object.__setattr__(
            self, "attempt", non_negative_int_or_none(self.attempt, "attempt")
        )
        object.__setattr__(
            self,
            "prior_fingerprint",
            optional_fingerprint_record(self.prior_fingerprint, "prior_fingerprint"),
        )
        object.__setattr__(
            self,
            "current_fingerprint",
            optional_fingerprint_record(
                self.current_fingerprint, "current_fingerprint"
            ),
        )
        object.__setattr__(self, "inputs", artifact_ref_mapping(self.inputs, "inputs"))
        object.__setattr__(
            self, "outputs", artifact_ref_mapping(self.outputs, "outputs")
        )
        object.__setattr__(self, "reasons", reason_tuple(self.reasons, "reasons"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "stage_name": self.stage_name,
            "action": self.action.value,
            "status": self.status,
            "attempt": self.attempt,
            "prior_fingerprint": self.prior_fingerprint.to_dict()
            if self.prior_fingerprint
            else None,
            "current_fingerprint": self.current_fingerprint.to_dict()
            if self.current_fingerprint
            else None,
            "inputs": {name: ref.to_dict() for name, ref in self.inputs.items()},
            "outputs": {name: ref.to_dict() for name, ref in self.outputs.items()},
            "reasons": [reason.to_dict() for reason in self.reasons],
        }

    @classmethod
    def from_dict(cls, data: object) -> "ResumeCheck":
        mapping = require_mapping(data, "ResumeCheck")
        allowed = {
            "stage_name",
            "action",
            "status",
            "attempt",
            "prior_fingerprint",
            "current_fingerprint",
            "inputs",
            "outputs",
            "reasons",
        }
        reject_unknown(mapping, allowed, "ResumeCheck")
        require_fields(mapping, allowed, "ResumeCheck")
        return cls(
            stage_name=require_str(mapping["stage_name"], "stage_name"),
            action=coerce_plan_action(mapping["action"]),
            status=optional_str(mapping.get("status"), "status"),
            attempt=non_negative_int_or_none(mapping.get("attempt"), "attempt"),
            prior_fingerprint=optional_fingerprint_record(
                mapping.get("prior_fingerprint"), "prior_fingerprint"
            ),
            current_fingerprint=optional_fingerprint_record(
                mapping.get("current_fingerprint"), "current_fingerprint"
            ),
            inputs=artifact_ref_mapping(mapping["inputs"], "inputs"),
            outputs=artifact_ref_mapping(mapping["outputs"], "outputs"),
            reasons=reason_tuple(mapping["reasons"], "reasons"),
        )


@dataclass(frozen=True, slots=True)
class StagePlan:
    stage_name: str
    action: PlanAction
    base_action: PlanAction
    fingerprint_status: FingerprintStatus
    fingerprint: StageFingerprintRecord | None
    resume_check: ResumeCheck | None
    reasons: tuple[PlanReason, ...]
    bound_inputs: Mapping[str, BoundInput]
    pending_inputs: tuple[PendingInput, ...]
    reusable_outputs: Mapping[str, ArtifactRef]
    declared_outputs: Mapping[str, Mapping[str, PlainData]]
    upstream_stages: tuple[str, ...]
    downstream_stages: tuple[str, ...]
    selected_by: tuple[PlanReasonCode, ...]
    invalidated_by: tuple[PlanReason, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "stage_name", require_str(self.stage_name, "stage_name")
        )
        object.__setattr__(self, "action", coerce_plan_action(self.action))
        object.__setattr__(self, "base_action", coerce_plan_action(self.base_action))
        object.__setattr__(
            self,
            "fingerprint_status",
            coerce_fingerprint_status(self.fingerprint_status),
        )
        object.__setattr__(
            self,
            "fingerprint",
            optional_fingerprint_record(self.fingerprint, "fingerprint"),
        )
        object.__setattr__(
            self,
            "resume_check",
            optional_resume_check(self.resume_check, "resume_check"),
        )
        object.__setattr__(self, "reasons", reason_tuple(self.reasons, "reasons"))
        object.__setattr__(
            self, "bound_inputs", bound_input_mapping(self.bound_inputs, "bound_inputs")
        )
        object.__setattr__(
            self,
            "pending_inputs",
            pending_input_tuple(self.pending_inputs, "pending_inputs"),
        )
        object.__setattr__(
            self,
            "reusable_outputs",
            artifact_ref_mapping(self.reusable_outputs, "reusable_outputs"),
        )
        object.__setattr__(
            self,
            "declared_outputs",
            nested_plain_mapping(self.declared_outputs, "declared_outputs"),
        )
        object.__setattr__(
            self, "upstream_stages", str_tuple(self.upstream_stages, "upstream_stages")
        )
        object.__setattr__(
            self,
            "downstream_stages",
            str_tuple(self.downstream_stages, "downstream_stages"),
        )
        object.__setattr__(
            self, "selected_by", reason_code_tuple(self.selected_by, "selected_by")
        )
        object.__setattr__(
            self, "invalidated_by", reason_tuple(self.invalidated_by, "invalidated_by")
        )
        if (
            self.fingerprint_status == FingerprintStatus.PENDING_INPUTS
            and self.fingerprint is not None
        ):
            raise PlanningValidationError(
                "pending-input stage plans must not include a computed fingerprint"
            )
        if self.action == PlanAction.REUSE and self.fingerprint is None:
            raise PlanningValidationError(
                "REUSE stage plans require a computed fingerprint"
            )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "stage_name": self.stage_name,
            "action": self.action.value,
            "base_action": self.base_action.value,
            "fingerprint_status": self.fingerprint_status.value,
            "fingerprint": self.fingerprint.to_dict() if self.fingerprint else None,
            "resume_check": self.resume_check.to_dict() if self.resume_check else None,
            "reasons": [reason.to_dict() for reason in self.reasons],
            "bound_inputs": {
                name: item.to_dict() for name, item in self.bound_inputs.items()
            },
            "pending_inputs": [item.to_dict() for item in self.pending_inputs],
            "reusable_outputs": {
                name: ref.to_dict() for name, ref in self.reusable_outputs.items()
            },
            "declared_outputs": {
                name: dict(value) for name, value in self.declared_outputs.items()
            },
            "upstream_stages": list(self.upstream_stages),
            "downstream_stages": list(self.downstream_stages),
            "selected_by": [code.value for code in self.selected_by],
            "invalidated_by": [reason.to_dict() for reason in self.invalidated_by],
        }

    @classmethod
    def from_dict(cls, data: object) -> "StagePlan":
        mapping = require_mapping(data, "StagePlan")
        allowed = {
            "stage_name",
            "action",
            "base_action",
            "fingerprint_status",
            "fingerprint",
            "resume_check",
            "reasons",
            "bound_inputs",
            "pending_inputs",
            "reusable_outputs",
            "declared_outputs",
            "upstream_stages",
            "downstream_stages",
            "selected_by",
            "invalidated_by",
        }
        reject_unknown(mapping, allowed, "StagePlan")
        require_fields(mapping, allowed, "StagePlan")
        return cls(
            stage_name=require_str(mapping["stage_name"], "stage_name"),
            action=coerce_plan_action(mapping["action"]),
            base_action=coerce_plan_action(mapping["base_action"]),
            fingerprint_status=coerce_fingerprint_status(mapping["fingerprint_status"]),
            fingerprint=optional_fingerprint_record(
                mapping.get("fingerprint"), "fingerprint"
            ),
            resume_check=optional_resume_check(
                mapping.get("resume_check"), "resume_check"
            ),
            reasons=reason_tuple(mapping["reasons"], "reasons"),
            bound_inputs=bound_input_mapping(mapping["bound_inputs"], "bound_inputs"),
            pending_inputs=pending_input_tuple(
                mapping["pending_inputs"], "pending_inputs"
            ),
            reusable_outputs=artifact_ref_mapping(
                mapping["reusable_outputs"], "reusable_outputs"
            ),
            declared_outputs=nested_plain_mapping(
                mapping["declared_outputs"], "declared_outputs"
            ),
            upstream_stages=str_tuple(mapping["upstream_stages"], "upstream_stages"),
            downstream_stages=str_tuple(
                mapping["downstream_stages"], "downstream_stages"
            ),
            selected_by=reason_code_tuple(mapping["selected_by"], "selected_by"),
            invalidated_by=reason_tuple(mapping["invalidated_by"], "invalidated_by"),
        )


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    schema_version: int
    run_id: str
    pipeline_name: str | None
    selectors: PlanSelectors
    resume: ResumeOptions
    fingerprint_context: FingerprintContext
    stage_order: tuple[str, ...]
    stage_plans: tuple[StagePlan, ...]
    reasons: tuple[PlanReason, ...]
    summary: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "schema_version", positive_int(self.schema_version, "schema_version")
        )
        object.__setattr__(self, "run_id", require_str(self.run_id, "run_id"))
        object.__setattr__(
            self, "pipeline_name", optional_str(self.pipeline_name, "pipeline_name")
        )
        object.__setattr__(
            self, "selectors", plan_selectors(self.selectors, "selectors")
        )
        object.__setattr__(self, "resume", resume_options(self.resume, "resume"))
        object.__setattr__(
            self,
            "fingerprint_context",
            fingerprint_context(self.fingerprint_context, "fingerprint_context"),
        )
        object.__setattr__(
            self, "stage_order", str_tuple(self.stage_order, "stage_order")
        )
        object.__setattr__(
            self, "stage_plans", stage_plan_tuple(self.stage_plans, "stage_plans")
        )
        object.__setattr__(self, "reasons", reason_tuple(self.reasons, "reasons"))
        object.__setattr__(self, "summary", int_mapping(self.summary, "summary"))
        if len(self.stage_order) != len(self.stage_plans):
            raise PlanningValidationError(
                "ExecutionPlan.stage_order and stage_plans must have the same length"
            )
        if set(self.stage_order) != {plan.stage_name for plan in self.stage_plans}:
            raise PlanningValidationError(
                "ExecutionPlan.stage_order must match stage plan names"
            )

    @property
    def ordered_stage_plans(self) -> tuple[StagePlan, ...]:
        by_name = {stage_plan.stage_name: stage_plan for stage_plan in self.stage_plans}
        return tuple(by_name[stage_name] for stage_name in self.stage_order)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "kind": "loom.execution_plan",
            "run_id": self.run_id,
            "pipeline_name": self.pipeline_name,
            "selectors": self.selectors.to_dict(),
            "resume": self.resume.to_dict(),
            "fingerprint_context": self.fingerprint_context.to_dict(),
            "stage_order": list(self.stage_order),
            "stage_plans": [plan.to_dict() for plan in self.ordered_stage_plans],
            "reasons": [reason.to_dict() for reason in self.reasons],
            "summary": dict(self.summary),
        }

    @classmethod
    def from_dict(cls, data: object) -> "ExecutionPlan":
        mapping = require_mapping(data, "ExecutionPlan")
        allowed = {
            "schema_version",
            "kind",
            "run_id",
            "pipeline_name",
            "selectors",
            "resume",
            "fingerprint_context",
            "stage_order",
            "stage_plans",
            "reasons",
            "summary",
        }
        reject_unknown(mapping, allowed, "ExecutionPlan")
        require_fields(mapping, allowed, "ExecutionPlan")
        if mapping["kind"] != "loom.execution_plan":
            raise PlanSerializationError(
                "ExecutionPlan.kind must be 'loom.execution_plan'"
            )
        return cls(
            schema_version=positive_int(mapping["schema_version"], "schema_version"),
            run_id=require_str(mapping["run_id"], "run_id"),
            pipeline_name=optional_str(mapping.get("pipeline_name"), "pipeline_name"),
            selectors=plan_selectors(mapping["selectors"], "selectors"),
            resume=resume_options(mapping["resume"], "resume"),
            fingerprint_context=fingerprint_context(
                mapping["fingerprint_context"], "fingerprint_context"
            ),
            stage_order=str_tuple(mapping["stage_order"], "stage_order"),
            stage_plans=stage_plan_tuple(mapping["stage_plans"], "stage_plans"),
            reasons=reason_tuple(mapping["reasons"], "reasons"),
            summary=int_mapping(mapping["summary"], "summary"),
        )


def summary_for(stage_plans: Sequence[StagePlan]) -> dict[str, int]:
    summary = {action.value: 0 for action in PlanAction}
    for stage_plan in stage_plans:
        summary[stage_plan.action.value] += 1
    return summary


def coerce_plan_action(value: object) -> PlanAction:
    if isinstance(value, PlanAction):
        return value
    if not isinstance(value, str):
        raise PlanningValidationError("plan action must be a string")
    try:
        return PlanAction(value)
    except ValueError as exc:
        raise PlanningValidationError(f"invalid plan action {value!r}") from exc


def coerce_fingerprint_status(value: object) -> FingerprintStatus:
    if isinstance(value, FingerprintStatus):
        return value
    if not isinstance(value, str):
        raise PlanningValidationError("fingerprint status must be a string")
    try:
        return FingerprintStatus(value)
    except ValueError as exc:
        raise PlanningValidationError(f"invalid fingerprint status {value!r}") from exc


def coerce_reason_code(value: object) -> PlanReasonCode:
    if isinstance(value, PlanReasonCode):
        return value
    if not isinstance(value, str):
        raise PlanningValidationError("plan reason code must be a string")
    try:
        return PlanReasonCode(value)
    except ValueError as exc:
        raise PlanningValidationError(f"invalid plan reason code {value!r}") from exc


def require_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise PlanningValidationError(f"{field} must be a non-empty string")
    return value


def optional_str(value: object | None, field: str) -> str | None:
    if value is None:
        return None
    return require_str(value, field)


def require_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise PlanningValidationError(f"{field} must be a bool")
    return value


def positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PlanningValidationError(f"{field} must be a positive integer")
    return value


def non_negative_int_or_none(value: object | None, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PlanningValidationError(f"{field} must be null or a non-negative integer")
    return value


def str_tuple(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise PlanningValidationError(f"{field} must be a sequence of strings")
    return tuple(require_str(item, f"{field} item") for item in value)


def plain_mapping(value: object, field: str) -> dict[str, PlainData]:
    try:
        plain = ensure_plain_data(value, path=field)
    except PlainDataError as exc:
        raise PlanningValidationError(
            f"{field} must be plain-data-compatible: {exc}"
        ) from exc
    if not isinstance(plain, dict):
        raise PlanningValidationError(f"{field} must be a mapping")
    return cast(dict[str, PlainData], dict(plain))


def str_mapping(value: object, field: str) -> dict[str, str]:
    mapping = require_mapping(value, field)
    return {
        require_str(key, f"{field} key"): require_str(item, f"{field}[{key!r}]")
        for key, item in mapping.items()
    }


def nested_plain_mapping(
    value: object, field: str
) -> dict[str, Mapping[str, PlainData]]:
    mapping = require_mapping(value, field)
    return {
        require_str(key, f"{field} key"): plain_mapping(item, f"{field}[{key!r}]")
        for key, item in mapping.items()
    }


def int_mapping(value: object, field: str) -> dict[str, int]:
    mapping = require_mapping(value, field)
    result: dict[str, int] = {}
    for key, item in mapping.items():
        key_text = require_str(key, f"{field} key")
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise PlanningValidationError(
                f"{field}[{key_text!r}] must be a non-negative integer"
            )
        result[key_text] = item
    return result


def artifact_ref(value: object, field: str) -> ArtifactRef:
    if isinstance(value, ArtifactRef):
        return value
    try:
        return ArtifactRef.from_dict(value)
    except ArtifactValidationError as exc:
        raise PlanSerializationError(
            f"{field} contains invalid ArtifactRef: {exc}"
        ) from exc


def artifact_ref_mapping(value: object, field: str) -> dict[str, ArtifactRef]:
    mapping = require_mapping(value, field)
    return {
        require_str(key, f"{field} key"): artifact_ref(item, f"{field}[{key!r}]")
        for key, item in mapping.items()
    }


def plan_reason(value: object, field: str) -> PlanReason:
    if isinstance(value, PlanReason):
        return value
    return PlanReason.from_dict(value)


def reason_tuple(value: object, field: str) -> tuple[PlanReason, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise PlanningValidationError(
            f"{field} must be a sequence of PlanReason values"
        )
    return tuple(plan_reason(item, f"{field} item") for item in value)


def reason_code_tuple(value: object, field: str) -> tuple[PlanReasonCode, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise PlanningValidationError(
            f"{field} must be a sequence of PlanReasonCode values"
        )
    return tuple(coerce_reason_code(item) for item in value)


def bound_input(value: object, field: str) -> BoundInput:
    if isinstance(value, BoundInput):
        return value
    return BoundInput.from_dict(value)


def bound_input_mapping(value: object, field: str) -> dict[str, BoundInput]:
    mapping = require_mapping(value, field)
    return {
        require_str(key, f"{field} key"): bound_input(item, f"{field}[{key!r}]")
        for key, item in mapping.items()
    }


def pending_input(value: object, field: str) -> PendingInput:
    if isinstance(value, PendingInput):
        return value
    return PendingInput.from_dict(value)


def pending_input_tuple(value: object, field: str) -> tuple[PendingInput, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise PlanningValidationError(
            f"{field} must be a sequence of PendingInput values"
        )
    return tuple(pending_input(item, f"{field} item") for item in value)


def fingerprint_payload(value: object, field: str) -> StageFingerprintPayload:
    if isinstance(value, StageFingerprintPayload):
        return value
    return StageFingerprintPayload.from_dict(value)


def optional_fingerprint_record(
    value: object, field: str
) -> StageFingerprintRecord | None:
    if value is None:
        return None
    if isinstance(value, StageFingerprintRecord):
        return value
    return StageFingerprintRecord.from_dict(value)


def optional_resume_check(value: object, field: str) -> ResumeCheck | None:
    if value is None:
        return None
    if isinstance(value, ResumeCheck):
        return value
    return ResumeCheck.from_dict(value)


def plan_selectors(value: object, field: str) -> PlanSelectors:
    if isinstance(value, PlanSelectors):
        return value
    return PlanSelectors.from_dict(value)


def resume_options(value: object, field: str) -> ResumeOptions:
    if isinstance(value, ResumeOptions):
        return value
    return ResumeOptions.from_dict(value)


def fingerprint_context(value: object, field: str) -> FingerprintContext:
    if isinstance(value, FingerprintContext):
        return value
    return FingerprintContext.from_dict(value)


def stage_plan(value: object, field: str) -> StagePlan:
    if isinstance(value, StagePlan):
        return value
    return StagePlan.from_dict(value)


def stage_plan_tuple(value: object, field: str) -> tuple[StagePlan, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise PlanningValidationError(f"{field} must be a sequence of StagePlan values")
    return tuple(stage_plan(item, f"{field} item") for item in value)


def require_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PlanSerializationError(f"{field} must be a mapping")
    return cast(Mapping[str, object], value)


def reject_unknown(
    mapping: Mapping[str, object], allowed: set[str], field: str
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise PlanSerializationError(
            f"{field} received unknown field(s): {', '.join(sorted(unknown))}"
        )


def require_fields(
    mapping: Mapping[str, object], required: set[str], field: str
) -> None:
    missing = required - set(mapping)
    if missing:
        raise PlanSerializationError(
            f"{field} missing required field(s): {', '.join(sorted(missing))}"
        )


__all__ = [
    "PLAN_SCHEMA_VERSION",
    "STAGE_FINGERPRINT_SCHEMA_VERSION",
    "STAGE_FINGERPRINT_POLICY_NAME",
    "STAGE_FINGERPRINT_POLICY_VERSION",
    "DEFAULT_FINGERPRINT_ALGORITHM",
    "PlanAction",
    "FingerprintStatus",
    "PlanReasonCode",
    "PlanReason",
    "PlanSelectors",
    "ResumeOptions",
    "FingerprintContext",
    "BoundInput",
    "PendingInput",
    "StageFingerprintPayload",
    "StageFingerprintRecord",
    "ResumeCheck",
    "StagePlan",
    "ExecutionPlan",
    "summary_for",
]
