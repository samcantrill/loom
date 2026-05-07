"""Safe runtime metadata and resolved stage runtime handoff models."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, cast

from loom.serialization import PlainData, ensure_plain_data, freeze_plain_data, thaw_plain_data
from loom.serialization.errors import PlainDataError

from loom.pipeline.errors import RuntimeResourceError
from loom.pipeline.resources import ResourceEntry, ResourceRequest, parse_resource_request
from loom.pipeline.runtime.environment import (
    RunEnvironmentRequest,
    StageEnvironmentRequest,
)
from loom.pipeline.runtime.options import (
    ExecutionOptions,
    RunOptions,
    StageRuntimeOptions,
    parse_run_options,
    validate_stage_runtime_options,
)

RUNTIME_METADATA_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ResolvedStageRuntimeOptions:
    """Executor-facing runtime policy for one canonical stage."""

    stage_id: str
    executor: str = "local"
    resources: ResourceRequest | Mapping[str, object] = field(default_factory=ResourceRequest)
    execution: ExecutionOptions | Mapping[str, object] = field(default_factory=ExecutionOptions)
    run_environment: RunEnvironmentRequest | Mapping[str, object] = field(
        default_factory=RunEnvironmentRequest
    )
    stage_environment: StageEnvironmentRequest | Mapping[str, object] = field(
        default_factory=StageEnvironmentRequest
    )
    adapter_options: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage_id", _non_empty_string(self.stage_id, "stage_id"))
        object.__setattr__(self, "executor", _non_empty_string(self.executor, "executor"))
        object.__setattr__(self, "resources", _coerce_resources(self.resources))
        object.__setattr__(self, "execution", _coerce_execution(self.execution))
        object.__setattr__(
            self,
            "run_environment",
            _coerce_run_environment(self.run_environment),
        )
        object.__setattr__(
            self,
            "stage_environment",
            _coerce_stage_environment(self.stage_environment),
        )
        object.__setattr__(
            self,
            "adapter_options",
            _freeze_plain_mapping(self.adapter_options, "adapter_options"),
        )

    def to_safe_metadata(self) -> dict[str, PlainData]:
        resources = cast(ResourceRequest, self.resources)
        execution = cast(ExecutionOptions, self.execution)
        run_environment = cast(RunEnvironmentRequest, self.run_environment)
        stage_environment = cast(StageEnvironmentRequest, self.stage_environment)
        return {
            "stage_id": self.stage_id,
            "executor": self.executor,
            "resources": _resource_request_metadata(resources),
            "execution": execution.to_safe_metadata(),
            "environment": {
                "run": run_environment.to_safe_metadata(),
                "stage": stage_environment.to_safe_metadata(),
            },
            "adapter_options": _adapter_metadata(self.adapter_options),
        }


@dataclass(frozen=True, slots=True)
class RuntimeMetadata:
    """Safe run-level runtime metadata for ``runtime.json``."""

    options: RunOptions | Mapping[str, object] = field(default_factory=RunOptions)
    stages: Mapping[str, ResolvedStageRuntimeOptions | Mapping[str, object]] = field(
        default_factory=dict
    )
    schema_version: int = RUNTIME_METADATA_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))
        options = parse_run_options(self.options)
        object.__setattr__(self, "options", options)
        object.__setattr__(self, "stages", _stage_mapping(self.stages))

    def to_dict(self) -> dict[str, PlainData]:
        options = cast(RunOptions, self.options)
        execution = cast(ExecutionOptions, options.execution)
        run_environment = cast(RunEnvironmentRequest, options.environment)
        stages = cast(Mapping[str, ResolvedStageRuntimeOptions], self.stages)
        return {
            "schema_version": self.schema_version,
            "options_schema_version": options.schema_version,
            "run_uri": options.run_uri,
            "executor": options.executor or "local",
            "dry_run": options.dry_run,
            "profile": options.profile,
            "tags": dict(options.tags),
            "notes": list(options.notes),
            "selectors": options.to_plan_selectors().to_dict(),
            "resume": options.to_resume_options().to_dict(),
            "execution": execution.to_safe_metadata(),
            "environment": run_environment.to_safe_metadata(),
            "adapter_options": _adapter_metadata(options.adapter_options),
            "stages": {
                stage_id: stage.to_safe_metadata()
                for stage_id, stage in stages.items()
            },
        }


def resolve_run_runtime(
    options: RunOptions | Mapping[str, object] | None = None,
    *,
    stage_ids: Iterable[str],
) -> Mapping[str, ResolvedStageRuntimeOptions]:
    """Resolve normalized runtime options into per-stage executor handoffs."""

    normalized = parse_run_options(options)
    stage_id_tuple = tuple(_non_empty_string(stage_id, "stage_ids") for stage_id in stage_ids)
    validate_stage_runtime_options(normalized, known_stage_ids=stage_id_tuple)
    run_execution = cast(ExecutionOptions, normalized.execution)
    run_environment = cast(RunEnvironmentRequest, normalized.environment)
    executor = normalized.executor or "local"
    resolved: dict[str, ResolvedStageRuntimeOptions] = {}
    for stage_id in stage_id_tuple:
        stage_runtime = cast(
            Mapping[str, StageRuntimeOptions],
            normalized.stage_options,
        ).get(stage_id, StageRuntimeOptions())
        stage_execution = cast(ExecutionOptions, stage_runtime.execution)
        stage_adapter_options = _merge_plain_mappings(
            normalized.adapter_options,
            stage_runtime.adapter_options,
        )
        resolved[stage_id] = ResolvedStageRuntimeOptions(
            stage_id=stage_id,
            executor=executor,
            resources=stage_runtime.resources,
            execution=ExecutionOptions(
                settings={
                    **run_execution.settings,
                    **stage_execution.settings,
                }
            ),
            run_environment=run_environment,
            stage_environment=stage_runtime.environment,
            adapter_options=stage_adapter_options,
        )
    return MappingProxyType(dict(sorted(resolved.items())))


def build_runtime_metadata(
    options: RunOptions | Mapping[str, object] | None,
    *,
    stage_ids: Iterable[str],
) -> RuntimeMetadata:
    """Build safe metadata from normalized run options and canonical stages."""

    normalized = parse_run_options(options)
    resolved = resolve_run_runtime(normalized, stage_ids=stage_ids)
    return RuntimeMetadata(options=normalized, stages=resolved)


def _stage_mapping(
    stages: Mapping[str, ResolvedStageRuntimeOptions | Mapping[str, object]],
) -> Mapping[str, ResolvedStageRuntimeOptions]:
    if not isinstance(stages, Mapping):
        raise RuntimeResourceError("RuntimeMetadata.stages must be a mapping")
    resolved: dict[str, ResolvedStageRuntimeOptions] = {}
    for key, value in stages.items():
        stage_id = _non_empty_string(key, "RuntimeMetadata.stages key")
        if isinstance(value, ResolvedStageRuntimeOptions):
            stage = value
        else:
            stage = ResolvedStageRuntimeOptions(
                stage_id=stage_id,
                **cast(
                    Any,
                    _object_mapping(value, f"RuntimeMetadata.stages[{stage_id!r}]"),
                ),
            )
        if stage.stage_id != stage_id:
            raise RuntimeResourceError(
                f"RuntimeMetadata.stages[{stage_id!r}] has mismatched stage_id {stage.stage_id!r}"
            )
        resolved[stage_id] = stage
    return MappingProxyType(dict(sorted(resolved.items())))


def _coerce_resources(value: object) -> ResourceRequest:
    if isinstance(value, ResourceRequest):
        return value
    mapping = _object_mapping(value, "resources")
    if "schema_version" in mapping:
        return ResourceRequest.from_dict(mapping)
    return parse_resource_request(mapping)


def _coerce_execution(value: object) -> ExecutionOptions:
    if isinstance(value, ExecutionOptions):
        return value
    return ExecutionOptions.from_dict(_object_mapping(value, "execution"))


def _coerce_run_environment(value: object) -> RunEnvironmentRequest:
    if isinstance(value, RunEnvironmentRequest):
        return value
    return RunEnvironmentRequest.from_dict(_object_mapping(value, "run_environment"))


def _coerce_stage_environment(value: object) -> StageEnvironmentRequest:
    if isinstance(value, StageEnvironmentRequest):
        return value
    return StageEnvironmentRequest.from_dict(_object_mapping(value, "stage_environment"))


def _resource_request_metadata(resources: ResourceRequest) -> dict[str, PlainData]:
    return {
        "schema_version": resources.schema_version,
        "entries": {
            kind: _resource_entry_metadata(entry)
            for kind, entry in resources.entries.items()
        },
    }


def _resource_entry_metadata(entry: ResourceEntry) -> dict[str, PlainData]:
    return {
        "kind": entry.kind,
        "amount": entry.amount,
        "unit": entry.unit,
        "attribute_count": len(entry.attributes),
    }


def _adapter_metadata(adapter_options: Mapping[str, PlainData]) -> dict[str, PlainData]:
    return {
        "namespace_count": len(adapter_options),
        "namespaces": cast(list[PlainData], sorted(adapter_options)),
    }


def _merge_plain_mappings(
    first: Mapping[str, PlainData],
    second: Mapping[str, PlainData],
) -> Mapping[str, PlainData]:
    return _freeze_plain_mapping({**first, **second}, "adapter_options")


def _freeze_plain_mapping(value: Mapping[str, PlainData], path: str) -> Mapping[str, PlainData]:
    try:
        normalized = ensure_plain_data(thaw_plain_data(dict(value), path=path), path=path)
    except PlainDataError as exc:
        raise RuntimeResourceError(f"{path} must be plain data: {exc}") from exc
    if not isinstance(normalized, dict):
        raise RuntimeResourceError(f"{path} must be a mapping")
    return cast(
        Mapping[str, PlainData],
        freeze_plain_data(normalized, path=path),
    )


def _object_mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RuntimeResourceError(f"{path} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise RuntimeResourceError(f"{path} must be a mapping with string keys")
    return cast(Mapping[str, object], value)


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeResourceError(f"{field} must be a non-empty string")
    return value


def _schema_version(value: object) -> int:
    if value != RUNTIME_METADATA_SCHEMA_VERSION:
        raise RuntimeResourceError(
            f"RuntimeMetadata.schema_version must be {RUNTIME_METADATA_SCHEMA_VERSION}"
        )
    return cast(int, value)


__all__ = [
    "RUNTIME_METADATA_SCHEMA_VERSION",
    "ResolvedStageRuntimeOptions",
    "RuntimeMetadata",
    "build_runtime_metadata",
    "resolve_run_runtime",
]
