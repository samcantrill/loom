"""Public runtime invocation option models."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

from loom.serialization import PlainData, ensure_plain_data, freeze_plain_data, thaw_plain_data
from loom.serialization.errors import PlainDataError

from loom.pipeline.errors import RuntimeResourceError
from loom.pipeline.resources import ResourceEntry, ResourceRequest, parse_resource_request
from loom.pipeline.reliability import ReliabilityPolicy
from loom.pipeline.runtime.environment import RunEnvironmentRequest, StageEnvironmentRequest

if TYPE_CHECKING:
    from loom.pipeline.planning.models import PlanSelectors, ResumeOptions

RUN_OPTIONS_SCHEMA_VERSION = 1
DEFAULT_MAX_PARALLEL_STAGES = 1
DEFAULT_FAILURE_POLICY = "stop_on_first_failure"
CONTINUE_INDEPENDENT_FAILURE_POLICY = "continue_independent"
_FAILURE_POLICY_ALIASES = {
    DEFAULT_FAILURE_POLICY: DEFAULT_FAILURE_POLICY,
    "stop-on-first-failure": DEFAULT_FAILURE_POLICY,
    CONTINUE_INDEPENDENT_FAILURE_POLICY: CONTINUE_INDEPENDENT_FAILURE_POLICY,
    "continue-independent": CONTINUE_INDEPENDENT_FAILURE_POLICY,
}

_RUN_OPTIONS_FIELDS = frozenset(
    {
        "schema_version",
        "run_uri",
        "executor",
        "dry_run",
        "profile",
        "tags",
        "notes",
        "selectors",
        "resume",
        "execution",
        "stage_options",
        "environment",
        "adapter_options",
        "reliability",
    }
)
_EXECUTION_OPTIONS_FIELDS = frozenset({"settings"})
_STAGE_RUNTIME_OPTIONS_FIELDS = frozenset(
    {"resources", "execution", "environment", "reliability", "adapter_options"}
)


def _default_plan_selectors() -> PlanSelectors:
    from loom.pipeline.planning.models import PlanSelectors

    return PlanSelectors()


def _default_resume_options() -> ResumeOptions:
    from loom.pipeline.planning.models import ResumeOptions

    return ResumeOptions()


@dataclass(frozen=True, slots=True)
class ExecutionOptions:
    """Plain execution settings preserved for future executor handoff."""

    settings: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "settings",
            _freeze_plain_mapping(
                _normalize_execution_settings(self.settings),
                path="ExecutionOptions.settings",
            ),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {"settings": _thaw_mapping(self.settings, path="ExecutionOptions.settings")}

    @classmethod
    def from_dict(cls, data: object) -> "ExecutionOptions":
        mapping = _object_mapping(data, path="ExecutionOptions")
        _reject_unknown(mapping, allowed=_EXECUTION_OPTIONS_FIELDS, path="ExecutionOptions")
        return cls(settings=_plain_mapping(mapping.get("settings", {}), path="ExecutionOptions.settings"))

    def to_safe_metadata(self) -> dict[str, PlainData]:
        return {"setting_keys": cast(list[PlainData], sorted(self.settings))}


@dataclass(frozen=True, slots=True)
class ParallelExecutionOptions:
    """Validated controller policy for local bounded stage execution."""

    max_parallel_stages: int = DEFAULT_MAX_PARALLEL_STAGES
    failure_policy: str = DEFAULT_FAILURE_POLICY

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_parallel_stages",
            _positive_int(
                self.max_parallel_stages,
                path="ParallelExecutionOptions.max_parallel_stages",
            ),
        )
        object.__setattr__(
            self,
            "failure_policy",
            _normalize_failure_policy(
                self.failure_policy,
                path="ParallelExecutionOptions.failure_policy",
            ),
        )

    @property
    def enabled(self) -> bool:
        return self.max_parallel_stages > 1

    @property
    def continue_independent(self) -> bool:
        return self.failure_policy == CONTINUE_INDEPENDENT_FAILURE_POLICY


@dataclass(frozen=True, slots=True)
class StageRuntimeOptions:
    """Exact-stage runtime options."""

    resources: ResourceRequest | Mapping[str, object] = field(default_factory=ResourceRequest)
    execution: ExecutionOptions | Mapping[str, object] = field(default_factory=ExecutionOptions)
    environment: StageEnvironmentRequest | Mapping[str, object] = field(
        default_factory=StageEnvironmentRequest
    )
    reliability: ReliabilityPolicy | Mapping[str, object] | None = None
    adapter_options: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "resources",
            _coerce_resource_request(self.resources, path="StageRuntimeOptions.resources"),
        )
        object.__setattr__(
            self,
            "execution",
            _coerce_execution_options(self.execution, path="StageRuntimeOptions.execution"),
        )
        object.__setattr__(
            self,
            "environment",
            _coerce_stage_environment(
                self.environment,
                path="StageRuntimeOptions.environment",
            ),
        )
        object.__setattr__(
            self,
            "reliability",
            _coerce_reliability(self.reliability, path="StageRuntimeOptions.reliability"),
        )
        object.__setattr__(
            self,
            "adapter_options",
            _freeze_plain_mapping(
                self.adapter_options,
                path="StageRuntimeOptions.adapter_options",
            ),
        )

    def to_dict(self) -> dict[str, PlainData]:
        resources = cast(ResourceRequest, self.resources)
        execution = cast(ExecutionOptions, self.execution)
        environment = cast(StageEnvironmentRequest, self.environment)
        reliability = cast(ReliabilityPolicy | None, self.reliability)
        payload: dict[str, PlainData] = {
            "resources": resources.to_dict(),
            "execution": execution.to_dict(),
            "environment": environment.to_dict(),
            "adapter_options": _thaw_mapping(
                self.adapter_options,
                path="StageRuntimeOptions.adapter_options",
            ),
        }
        if reliability is not None:
            payload["reliability"] = reliability.to_dict()
        return payload

    @classmethod
    def from_dict(cls, data: object) -> "StageRuntimeOptions":
        mapping = _object_mapping(data, path="StageRuntimeOptions")
        _reject_unknown(
            mapping,
            allowed=_STAGE_RUNTIME_OPTIONS_FIELDS,
            path="StageRuntimeOptions",
        )
        return cls(
            resources=_coerce_resource_request(
                mapping.get("resources"),
                path="StageRuntimeOptions.resources",
            ),
            execution=_coerce_execution_options(
                mapping.get("execution", {}),
                path="StageRuntimeOptions.execution",
            ),
            environment=_coerce_stage_environment(
                mapping.get("environment", {}),
                path="StageRuntimeOptions.environment",
            ),
            reliability=_coerce_reliability(
                mapping.get("reliability"),
                path="StageRuntimeOptions.reliability",
            ),
            adapter_options=_plain_mapping(
                mapping.get("adapter_options", {}),
                path="StageRuntimeOptions.adapter_options",
            ),
        )

    def to_safe_metadata(self) -> dict[str, PlainData]:
        resources = cast(ResourceRequest, self.resources)
        execution = cast(ExecutionOptions, self.execution)
        environment = cast(StageEnvironmentRequest, self.environment)
        reliability = cast(ReliabilityPolicy | None, self.reliability)
        return {
            "resources": _safe_resource_metadata(resources),
            "execution": execution.to_safe_metadata(),
            "environment": environment.to_safe_metadata(),
            **(
                {"reliability": reliability.to_dict()}
                if reliability is not None
                else {}
            ),
            "adapter_options": _safe_adapter_metadata(self.adapter_options),
        }


@dataclass(frozen=True, slots=True)
class RunOptions:
    """Canonical invocation policy for a pipeline run."""

    run_uri: str | None = None
    executor: str | None = None
    dry_run: bool = False
    profile: str | None = None
    tags: Mapping[str, str] = field(default_factory=dict)
    notes: Sequence[str] = ()
    selectors: PlanSelectors | Mapping[str, object] = field(default_factory=_default_plan_selectors)
    resume: ResumeOptions | Mapping[str, object] = field(default_factory=_default_resume_options)
    execution: ExecutionOptions | Mapping[str, object] = field(default_factory=ExecutionOptions)
    stage_options: Mapping[str, StageRuntimeOptions | Mapping[str, object]] = field(
        default_factory=dict
    )
    environment: RunEnvironmentRequest | Mapping[str, object] = field(
        default_factory=RunEnvironmentRequest
    )
    adapter_options: Mapping[str, PlainData] = field(default_factory=dict)
    reliability: ReliabilityPolicy | Mapping[str, object] | None = None
    schema_version: int = RUN_OPTIONS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_schema_version(self.schema_version, path="RunOptions.schema_version"),
        )
        object.__setattr__(self, "run_uri", _optional_string(self.run_uri, path="RunOptions.run_uri"))
        object.__setattr__(
            self,
            "executor",
            _optional_string(self.executor, path="RunOptions.executor"),
        )
        object.__setattr__(
            self,
            "dry_run",
            _bool_value(self.dry_run, path="RunOptions.dry_run"),
        )
        object.__setattr__(
            self,
            "profile",
            _optional_string(self.profile, path="RunOptions.profile"),
        )
        object.__setattr__(self, "tags", _str_mapping(self.tags, path="RunOptions.tags"))
        object.__setattr__(self, "notes", _str_tuple(self.notes, path="RunOptions.notes"))
        object.__setattr__(
            self,
            "selectors",
            _coerce_selectors(self.selectors, path="RunOptions.selectors"),
        )
        object.__setattr__(self, "resume", _coerce_resume(self.resume, path="RunOptions.resume"))
        object.__setattr__(
            self,
            "execution",
            _coerce_execution_options(self.execution, path="RunOptions.execution"),
        )
        object.__setattr__(
            self,
            "stage_options",
            _coerce_stage_options(self.stage_options, path="RunOptions.stage_options"),
        )
        object.__setattr__(
            self,
            "environment",
            _coerce_run_environment(self.environment, path="RunOptions.environment"),
        )
        object.__setattr__(
            self,
            "adapter_options",
            _freeze_plain_mapping(self.adapter_options, path="RunOptions.adapter_options"),
        )
        object.__setattr__(
            self,
            "reliability",
            _coerce_reliability(self.reliability, path="RunOptions.reliability"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        selectors = cast("PlanSelectors", self.selectors)
        resume = cast("ResumeOptions", self.resume)
        execution = cast(ExecutionOptions, self.execution)
        environment = cast(RunEnvironmentRequest, self.environment)
        reliability = cast(ReliabilityPolicy | None, self.reliability)
        return {
            "schema_version": self.schema_version,
            "run_uri": self.run_uri,
            "executor": self.executor,
            "dry_run": self.dry_run,
            "profile": self.profile,
            "tags": dict(self.tags),
            "notes": list(self.notes),
            "selectors": selectors.to_dict(),
            "resume": resume.to_dict(),
            "execution": execution.to_dict(),
            "stage_options": {
                stage_id: option.to_dict()
                for stage_id, option in cast(
                    Mapping[str, StageRuntimeOptions],
                    self.stage_options,
                ).items()
            },
            "environment": environment.to_dict(),
            **(
                {"reliability": reliability.to_dict()}
                if reliability is not None
                else {}
            ),
            "adapter_options": _thaw_mapping(self.adapter_options, path="RunOptions.adapter_options"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "RunOptions":
        mapping = _object_mapping(data, path="RunOptions")
        _reject_unknown(mapping, allowed=_RUN_OPTIONS_FIELDS, path="RunOptions")
        return cls(
            schema_version=_require_schema_version(
                mapping.get("schema_version", RUN_OPTIONS_SCHEMA_VERSION),
                path="RunOptions.schema_version",
            ),
            run_uri=_optional_string(mapping.get("run_uri"), path="RunOptions.run_uri"),
            executor=_optional_string(mapping.get("executor"), path="RunOptions.executor"),
            dry_run=_bool_value(mapping.get("dry_run", False), path="RunOptions.dry_run"),
            profile=_optional_string(mapping.get("profile"), path="RunOptions.profile"),
            tags=_str_mapping(mapping.get("tags", {}), path="RunOptions.tags"),
            notes=_str_tuple(mapping.get("notes", ()), path="RunOptions.notes"),
            selectors=_coerce_selectors(
                mapping.get("selectors", {}),
                path="RunOptions.selectors",
            ),
            resume=_coerce_resume(mapping.get("resume", {}), path="RunOptions.resume"),
            execution=_coerce_execution_options(
                mapping.get("execution", {}),
                path="RunOptions.execution",
            ),
            stage_options=_coerce_stage_options(
                mapping.get("stage_options", {}),
                path="RunOptions.stage_options",
            ),
            environment=_coerce_run_environment(
                mapping.get("environment", {}),
                path="RunOptions.environment",
            ),
            reliability=_coerce_reliability(
                mapping.get("reliability"),
                path="RunOptions.reliability",
            ),
            adapter_options=_plain_mapping(
                mapping.get("adapter_options", {}),
                path="RunOptions.adapter_options",
            ),
        )

    def to_plan_selectors(self) -> PlanSelectors:
        return cast("PlanSelectors", self.selectors)

    def to_resume_options(self) -> ResumeOptions:
        return cast("ResumeOptions", self.resume)

    def to_safe_metadata(self) -> dict[str, PlainData]:
        execution = cast(ExecutionOptions, self.execution)
        environment = cast(RunEnvironmentRequest, self.environment)
        selectors = cast("PlanSelectors", self.selectors)
        resume = cast("ResumeOptions", self.resume)
        reliability = cast(ReliabilityPolicy | None, self.reliability)
        return {
            "schema_version": self.schema_version,
            "run_uri": self.run_uri,
            "executor": self.executor,
            "dry_run": self.dry_run,
            "profile": self.profile,
            "tags": dict(self.tags),
            "notes": list(self.notes),
            "selectors": selectors.to_dict(),
            "resume": resume.to_dict(),
            "execution": execution.to_safe_metadata(),
            "stage_options": {
                stage_id: option.to_safe_metadata()
                for stage_id, option in cast(
                    Mapping[str, StageRuntimeOptions],
                    self.stage_options,
                ).items()
            },
            "environment": environment.to_safe_metadata(),
            "reliability": reliability.to_dict() if reliability is not None else None,
            "adapter_options": _safe_adapter_metadata(self.adapter_options),
        }


def parse_run_options(data: object | None) -> RunOptions:
    if data is None:
        return RunOptions()
    if isinstance(data, RunOptions):
        return data
    return RunOptions.from_dict(data)


def parallel_execution_options(options: RunOptions) -> ParallelExecutionOptions:
    """Return typed parallel execution controls from generic run settings."""

    execution = cast(ExecutionOptions, options.execution)
    return ParallelExecutionOptions(
        max_parallel_stages=cast(
            int,
            execution.settings.get(
                "max_parallel_stages",
                DEFAULT_MAX_PARALLEL_STAGES,
            ),
        ),
        failure_policy=cast(
            str,
            execution.settings.get("failure_policy", DEFAULT_FAILURE_POLICY),
        ),
    )


def validate_stage_runtime_options(
    options: RunOptions | Mapping[str, StageRuntimeOptions | Mapping[str, object]],
    *,
    known_stage_ids: Iterable[str] | None = None,
) -> None:
    if isinstance(options, RunOptions):
        stage_options = options.stage_options
    else:
        stage_options = _coerce_stage_options(options, path="stage_options")
    if known_stage_ids is None:
        return
    known = {_validate_stage_id(stage_id, path="known_stage_ids") for stage_id in known_stage_ids}
    unknown = sorted(set(stage_options) - known)
    if unknown:
        fields = ", ".join(unknown)
        raise RuntimeResourceError(f"stage_options target unknown stage id(s): {fields}")


def _coerce_resource_request(value: object, *, path: str) -> ResourceRequest:
    if value is None:
        return ResourceRequest()
    if isinstance(value, ResourceRequest):
        return value
    mapping = _object_mapping(value, path=path)
    if "schema_version" in mapping:
        return ResourceRequest.from_dict(mapping)
    return parse_resource_request(mapping)


def _coerce_execution_options(value: object, *, path: str) -> ExecutionOptions:
    if isinstance(value, ExecutionOptions):
        return value
    return ExecutionOptions.from_dict(_object_mapping(value, path=path))


def _coerce_stage_environment(value: object, *, path: str) -> StageEnvironmentRequest:
    if isinstance(value, StageEnvironmentRequest):
        return value
    return StageEnvironmentRequest.from_dict(_object_mapping(value, path=path))


def _coerce_run_environment(value: object, *, path: str) -> RunEnvironmentRequest:
    if isinstance(value, RunEnvironmentRequest):
        return value
    return RunEnvironmentRequest.from_dict(_object_mapping(value, path=path))


def _coerce_reliability(
    value: object,
    *,
    path: str,
) -> ReliabilityPolicy | None:
    if value is None:
        return None
    if isinstance(value, ReliabilityPolicy):
        return value
    return ReliabilityPolicy.from_dict(value)


def _coerce_selectors(value: object, *, path: str) -> PlanSelectors:
    from loom.pipeline.planning.models import PlanSelectors

    if isinstance(value, PlanSelectors):
        return value
    return PlanSelectors.from_dict(_object_mapping(value, path=path))


def _coerce_resume(value: object, *, path: str) -> ResumeOptions:
    from loom.pipeline.planning.models import ResumeOptions

    if isinstance(value, ResumeOptions):
        return value
    return ResumeOptions.from_dict(_object_mapping(value, path=path))


def _coerce_stage_options(
    value: object,
    *,
    path: str,
) -> Mapping[str, StageRuntimeOptions]:
    if not isinstance(value, Mapping):
        raise RuntimeResourceError(f"{path} must be a mapping")
    normalized: dict[str, StageRuntimeOptions] = {}
    for key, item in value.items():
        stage_id = _validate_stage_id(key, path=f"{path} key")
        if isinstance(item, StageRuntimeOptions):
            normalized[stage_id] = item
        else:
            normalized[stage_id] = StageRuntimeOptions.from_dict(
                _object_mapping(item, path=f"{path}[{stage_id!r}]")
            )
    return MappingProxyType(dict(sorted(normalized.items())))


def _validate_stage_id(value: object, *, path: str) -> str:
    text = _string_value(value, path=path)
    if value in {".", ".."}:
        raise RuntimeResourceError(f"{path} cannot be '.' or '..'")
    if "." in text:
        raise RuntimeResourceError(f"{path} cannot contain '.'")
    if "/" in text or "\\" in text:
        raise RuntimeResourceError(f"{path} cannot contain path separators")
    if any(ch <= " " for ch in text):
        raise RuntimeResourceError(f"{path} cannot contain control or whitespace characters")
    return text


def _object_mapping(value: object, *, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RuntimeResourceError(f"{path} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise RuntimeResourceError(f"{path} must be a mapping with string keys")
    return cast(Mapping[str, object], value)


def _plain_mapping(value: object, *, path: str) -> Mapping[str, PlainData]:
    try:
        normalized = ensure_plain_data(value, path=path)
    except PlainDataError as exc:
        raise RuntimeResourceError(f"{path} must be plain-data-compatible mapping: {exc}") from exc
    if not isinstance(normalized, Mapping):
        raise RuntimeResourceError(f"{path} must be a mapping")
    return cast(Mapping[str, PlainData], normalized)


def _normalize_execution_settings(value: object) -> Mapping[str, PlainData]:
    settings = dict(_plain_mapping(value, path="ExecutionOptions.settings"))
    if "max_parallel_stages" in settings:
        settings["max_parallel_stages"] = _positive_int(
            settings["max_parallel_stages"],
            path="ExecutionOptions.settings.max_parallel_stages",
        )
    if "failure_policy" in settings:
        settings["failure_policy"] = _normalize_failure_policy(
            settings["failure_policy"],
            path="ExecutionOptions.settings.failure_policy",
        )
    return settings


def _positive_int(value: object, *, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeResourceError(f"{path} must be a positive integer")
    if value <= 0:
        raise RuntimeResourceError(f"{path} must be a positive integer")
    return value


def _normalize_failure_policy(value: object, *, path: str) -> str:
    text = _string_value(value, path=path)
    try:
        return _FAILURE_POLICY_ALIASES[text]
    except KeyError as exc:
        choices = ", ".join(
            sorted({DEFAULT_FAILURE_POLICY, CONTINUE_INDEPENDENT_FAILURE_POLICY})
        )
        raise RuntimeResourceError(
            f"{path} must be one of: {choices}"
        ) from exc


def _freeze_plain_mapping(value: object, *, path: str) -> Mapping[str, PlainData]:
    return cast(
        Mapping[str, PlainData],
        freeze_plain_data(_sorted_plain_mapping(_plain_mapping(value, path=path)), path=path),
    )


def _thaw_mapping(value: Mapping[str, PlainData], *, path: str) -> dict[str, PlainData]:
    thawed = thaw_plain_data(value, path=path)
    if not isinstance(thawed, dict):
        raise RuntimeResourceError(f"{path} must be a mapping")
    return _sorted_plain_mapping(thawed)


def _sorted_plain_mapping(value: Mapping[str, PlainData]) -> dict[str, PlainData]:
    return {key: _sort_plain_value(value[key]) for key in sorted(value)}


def _sort_plain_value(value: PlainData) -> PlainData:
    if isinstance(value, dict):
        return _sorted_plain_mapping(value)
    if isinstance(value, list):
        return [_sort_plain_value(item) for item in value]
    return value


def _str_mapping(value: object, *, path: str) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise RuntimeResourceError(f"{path} must be a mapping")
    normalized: dict[str, str] = {}
    for key, item in value.items():
        name = _string_value(key, path=f"{path} key")
        if not isinstance(item, str):
            raise RuntimeResourceError(f"{path}[{name!r}] must be a string")
        normalized[name] = item
    return MappingProxyType(dict(sorted(normalized.items())))


def _str_tuple(value: object, *, path: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise RuntimeResourceError(f"{path} must be a sequence of strings")
    items: list[str] = []
    for index, item in enumerate(value):
        items.append(_string_value(item, path=f"{path}[{index}]"))
    return tuple(items)


def _safe_resource_metadata(resources: ResourceRequest) -> dict[str, PlainData]:
    return {
        "entries": {
            kind: _safe_resource_entry_metadata(entry)
            for kind, entry in resources.entries.items()
        }
    }


def _safe_resource_entry_metadata(entry: ResourceEntry) -> dict[str, PlainData]:
    return {
        "amount": entry.amount,
        "unit": entry.unit,
        "attribute_count": len(entry.attributes),
    }


def _safe_adapter_metadata(adapter_options: Mapping[str, PlainData]) -> dict[str, PlainData]:
    return {
        "namespace_count": len(adapter_options),
        "namespaces": cast(list[PlainData], sorted(adapter_options)),
    }


def _reject_unknown(
    mapping: Mapping[str, object],
    *,
    allowed: frozenset[str],
    path: str,
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise RuntimeResourceError(f"{path} contains unknown field(s): {fields}")


def _optional_string(value: object, *, path: str) -> str | None:
    if value is None:
        return None
    return _string_value(value, path=path)


def _string_value(value: object, *, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeResourceError(f"{path} must be a non-empty string")
    return value


def _bool_value(value: object, *, path: str) -> bool:
    if not isinstance(value, bool):
        raise RuntimeResourceError(f"{path} must be a bool")
    return value


def _require_schema_version(value: object, *, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeResourceError(f"{path} must be a positive integer")
    if value != RUN_OPTIONS_SCHEMA_VERSION:
        raise RuntimeResourceError(
            f"unsupported {path} {value!r}, expected {RUN_OPTIONS_SCHEMA_VERSION}"
        )
    return value


__all__ = [
    "CONTINUE_INDEPENDENT_FAILURE_POLICY",
    "DEFAULT_FAILURE_POLICY",
    "DEFAULT_MAX_PARALLEL_STAGES",
    "RUN_OPTIONS_SCHEMA_VERSION",
    "ExecutionOptions",
    "ParallelExecutionOptions",
    "RunOptions",
    "StageRuntimeOptions",
    "parallel_execution_options",
    "parse_run_options",
    "validate_stage_runtime_options",
]
