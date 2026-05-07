"""Runtime profile models and deterministic merge helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

from loom.serialization import PlainData, freeze_plain_data

from loom.pipeline.errors import RuntimeResourceError
from loom.pipeline.resources import ResourceRequest
from loom.pipeline.runtime.environment import RunEnvironmentRequest, StageEnvironmentRequest
from loom.pipeline.runtime.options import (
    ExecutionOptions,
    RunOptions,
    StageRuntimeOptions,
    _bool_value,
    _coerce_resource_request,
    _object_mapping,
    _optional_string,
    _plain_mapping,
    _reject_unknown,
    _require_schema_version,
    _str_mapping,
    _str_tuple,
    _thaw_mapping,
    _validate_stage_id,
    validate_stage_runtime_options,
)

_RUN_SOURCE_FIELDS = frozenset(
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
    }
)
_PROFILE_CORE_FIELDS = _RUN_SOURCE_FIELDS - {"schema_version", "profile"}
_PROFILE_RESERVED_FIELDS = frozenset({"schema_version", "profile"})
_SELECTOR_FIELDS = frozenset(
    {"force_stages", "from_stage", "only_stages", "skip_stages"}
)
_RESUME_FIELDS = frozenset({"enabled"})
_ENVIRONMENT_FIELDS = frozenset({"inherit", "set_variables", "unset_variables"})
_EXECUTION_FIELDS = frozenset({"settings"})
_STAGE_RUNTIME_FIELDS = frozenset(
    {"resources", "execution", "environment", "adapter_options"}
)

@dataclass(frozen=True, slots=True)
class RuntimeProfile:
    """Sparse runtime option defaults preserved as immutable plain data."""

    options: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "options",
            _freeze_source_mapping(
                _normalize_run_source(
                    self.options,
                    path="RuntimeProfile",
                    profile_source=True,
                ),
                path="RuntimeProfile",
            ),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return _thaw_mapping(
            cast(Mapping[str, PlainData], self.options),
            path="RuntimeProfile",
        )

    @classmethod
    def from_dict(cls, data: object) -> "RuntimeProfile":
        return cls(_object_mapping(data, path="RuntimeProfile"))


RunOptionsSource = RunOptions | RuntimeProfile | Mapping[str, object]


@dataclass(frozen=True, slots=True)
class RuntimeProfileCollection:
    """Named runtime profile collection with deterministic selection."""

    profiles: Mapping[str, RuntimeProfile | Mapping[str, object]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        mapping = _object_mapping(self.profiles, path="RuntimeProfileCollection")
        normalized: dict[str, RuntimeProfile] = {}
        for key, value in mapping.items():
            name = _profile_name(key, path="RuntimeProfileCollection key")
            if isinstance(value, RuntimeProfile):
                normalized[name] = value
            else:
                normalized[name] = RuntimeProfile.from_dict(value)
        object.__setattr__(
            self,
            "profiles",
            MappingProxyType(dict(sorted(normalized.items()))),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            name: profile.to_dict()
            for name, profile in cast(Mapping[str, RuntimeProfile], self.profiles).items()
        }

    @classmethod
    def from_dict(cls, data: object | None) -> "RuntimeProfileCollection":
        if data is None:
            return cls()
        return cls(
            cast(
                Mapping[str, RuntimeProfile | Mapping[str, object]],
                _object_mapping(data, path="RuntimeProfileCollection"),
            )
        )

    def select(self, name: str | None) -> RuntimeProfile | None:
        if name is None:
            return None
        normalized_name = _profile_name(name, path="runtime profile selection")
        profile = cast(Mapping[str, RuntimeProfile], self.profiles).get(normalized_name)
        if profile is None:
            raise RuntimeResourceError(
                f"runtime profile {normalized_name!r} is not defined"
            )
        return profile


def parse_runtime_profile(data: object | None) -> RuntimeProfile:
    if data is None:
        return RuntimeProfile()
    return RuntimeProfile.from_dict(data)


def parse_runtime_profiles(data: object | None) -> RuntimeProfileCollection:
    return RuntimeProfileCollection.from_dict(data)


def select_runtime_profile(
    profiles: RuntimeProfileCollection | Mapping[str, object] | None,
    name: str | None,
) -> RuntimeProfile | None:
    if name is None:
        return None
    collection = _coerce_profile_collection(profiles)
    if collection is None:
        normalized_name = _profile_name(name, path="runtime profile selection")
        raise RuntimeResourceError(
            f"runtime profile {normalized_name!r} was selected but no runtime profiles were supplied"
        )
    return collection.select(name)


def merge_run_options(
    *,
    base: RunOptionsSource | None = None,
    profiles: RuntimeProfileCollection | Mapping[str, object] | None = None,
    explicit: RunOptionsSource | None = None,
    profile: str | None = None,
    known_stage_ids: Iterable[str] | None = None,
) -> RunOptions:
    """Merge base, selected profile, and explicit runtime option sources."""

    base_source = _normalize_run_source(base, path="base")
    explicit_source = _normalize_run_source(explicit, path="explicit")
    direct_profile = _optional_profile_name(profile, path="profile")
    selected_profile = (
        direct_profile
        if direct_profile is not None
        else _selected_profile_name(base_source, explicit_source)
    )
    profile_model = select_runtime_profile(profiles, selected_profile)
    profile_source = (
        {}
        if profile_model is None
        else _normalize_run_source(profile_model, path=f"profiles[{selected_profile!r}]")
    )

    merged: dict[str, object] = {}
    _merge_run_source(merged, base_source)
    _merge_run_source(merged, profile_source)
    _merge_run_source(merged, explicit_source)
    if direct_profile is not None:
        merged["profile"] = direct_profile

    options = RunOptions.from_dict(merged)
    validate_stage_runtime_options(options, known_stage_ids=known_stage_ids)
    return options


def _coerce_profile_collection(
    profiles: RuntimeProfileCollection | Mapping[str, object] | None,
) -> RuntimeProfileCollection | None:
    if profiles is None:
        return None
    if isinstance(profiles, RuntimeProfileCollection):
        return profiles
    return RuntimeProfileCollection.from_dict(profiles)


def _selected_profile_name(
    base: Mapping[str, object],
    explicit: Mapping[str, object],
) -> str | None:
    selected = _source_profile_value(base)
    if "profile" in explicit:
        selected = cast(str | None, explicit["profile"])
    return selected


def _source_profile_value(source: Mapping[str, object]) -> str | None:
    if "profile" not in source:
        return None
    return cast(str | None, source["profile"])


def _normalize_run_source(
    source: RunOptionsSource | None,
    *,
    path: str,
    profile_source: bool = False,
) -> dict[str, object]:
    if source is None:
        return {}
    if isinstance(source, RuntimeProfile):
        return _object_dict(source.to_dict())
    if isinstance(source, RunOptions):
        return {
            key: value
            for key, value in source.to_dict().items()
            if key != "schema_version"
        }

    mapping = _object_mapping(source, path=path)
    if profile_source:
        reserved = set(mapping) & _PROFILE_RESERVED_FIELDS
        if reserved:
            fields = ", ".join(sorted(reserved))
            raise RuntimeResourceError(f"{path} contains reserved field(s): {fields}")
    else:
        _reject_unknown(mapping, allowed=_RUN_SOURCE_FIELDS, path=path)
        if "schema_version" in mapping:
            _require_schema_version(mapping["schema_version"], path=f"{path}.schema_version")

    normalized: dict[str, object] = {}
    adapter_sections: dict[str, PlainData] = {}
    for key, value in mapping.items():
        if key == "schema_version":
            continue
        if profile_source and key not in _PROFILE_CORE_FIELDS:
            adapter_sections[key] = _plain_adapter_payload(value, path=f"{path}.{key}")
            continue
        normalized[key] = _normalize_run_field(key, value, path=f"{path}.{key}")

    if adapter_sections:
        existing = cast(dict[str, PlainData], normalized.get("adapter_options", {}))
        duplicate = sorted(set(adapter_sections) & set(existing))
        if duplicate:
            fields = ", ".join(duplicate)
            raise RuntimeResourceError(
                f"{path} supplies duplicate adapter namespace(s): {fields}"
            )
        normalized["adapter_options"] = {**existing, **adapter_sections}

    return normalized


def _normalize_run_field(key: str, value: object, *, path: str) -> object:
    if key in {"run_uri", "executor", "profile"}:
        return _optional_string(value, path=path)
    if key == "dry_run":
        return _bool_value(value, path=path)
    if key == "tags":
        return dict(_str_mapping(value, path=path))
    if key == "notes":
        return list(_str_tuple(value, path=path))
    if key == "selectors":
        return _normalize_selectors(value, path=path)
    if key == "resume":
        return _normalize_resume(value, path=path)
    if key == "execution":
        return _normalize_execution(value, path=path)
    if key == "stage_options":
        return _normalize_stage_options(value, path=path)
    if key == "environment":
        return _normalize_environment(value, path=path, stage=False)
    if key == "adapter_options":
        return _plain_adapter_mapping(value, path=path)
    raise RuntimeResourceError(f"{path} is not a supported runtime option field")


def _normalize_selectors(value: object, *, path: str) -> dict[str, object]:
    from loom.pipeline.planning.errors import PlanningValidationError
    from loom.pipeline.planning.models import PlanSelectors

    if isinstance(value, PlanSelectors):
        return _object_dict(value.to_dict())
    mapping = _object_mapping(value, path=path)
    _reject_unknown(mapping, allowed=_SELECTOR_FIELDS, path=path)
    try:
        parsed = PlanSelectors.from_dict(mapping)
    except PlanningValidationError as exc:
        raise RuntimeResourceError(f"{path}: {exc}") from exc
    parsed_data = _object_dict(parsed.to_dict())
    return {key: parsed_data[key] for key in mapping}


def _normalize_resume(value: object, *, path: str) -> dict[str, object]:
    from loom.pipeline.planning.errors import PlanningValidationError
    from loom.pipeline.planning.models import ResumeOptions

    if isinstance(value, ResumeOptions):
        return _object_dict(value.to_dict())
    mapping = _object_mapping(value, path=path)
    _reject_unknown(mapping, allowed=_RESUME_FIELDS, path=path)
    try:
        parsed = ResumeOptions.from_dict(mapping)
    except PlanningValidationError as exc:
        raise RuntimeResourceError(f"{path}: {exc}") from exc
    parsed_data = _object_dict(parsed.to_dict())
    return {key: parsed_data[key] for key in mapping}


def _normalize_execution(value: object, *, path: str) -> dict[str, object]:
    if isinstance(value, ExecutionOptions):
        return _object_dict(value.to_dict())
    mapping = _object_mapping(value, path=path)
    _reject_unknown(mapping, allowed=_EXECUTION_FIELDS, path=path)
    parsed = ExecutionOptions.from_dict(mapping)
    if "settings" not in mapping:
        return {}
    return {"settings": dict(parsed.settings)}


def _normalize_environment(
    value: object,
    *,
    path: str,
    stage: bool,
) -> dict[str, object]:
    environment_type = StageEnvironmentRequest if stage else RunEnvironmentRequest
    if isinstance(value, environment_type):
        return _object_dict(value.to_dict())
    mapping = _object_mapping(value, path=path)
    _reject_unknown(mapping, allowed=_ENVIRONMENT_FIELDS, path=path)
    parsed = environment_type.from_dict(mapping)
    parsed_data = _object_dict(parsed.to_dict())
    return {key: parsed_data[key] for key in mapping}


def _normalize_stage_options(value: object, *, path: str) -> dict[str, object]:
    mapping = _object_mapping(value, path=path)
    normalized: dict[str, object] = {}
    for key, item in mapping.items():
        stage_id = _validate_stage_id(key, path=f"{path} key")
        normalized[stage_id] = _normalize_stage_runtime(
            item,
            path=f"{path}[{stage_id!r}]",
        )
    return normalized


def _normalize_stage_runtime(value: object, *, path: str) -> dict[str, object]:
    if isinstance(value, StageRuntimeOptions):
        return _object_dict(value.to_dict())
    mapping = _object_mapping(value, path=path)
    _reject_unknown(mapping, allowed=_STAGE_RUNTIME_FIELDS, path=path)
    normalized: dict[str, object] = {}
    for key, item in mapping.items():
        if key == "resources":
            normalized[key] = _normalize_resources(item, path=f"{path}.resources")
        elif key == "execution":
            normalized[key] = _normalize_execution(item, path=f"{path}.execution")
        elif key == "environment":
            normalized[key] = _normalize_environment(
                item,
                path=f"{path}.environment",
                stage=True,
            )
        elif key == "adapter_options":
            normalized[key] = _plain_adapter_mapping(
                item,
                path=f"{path}.adapter_options",
            )
    return normalized


def _normalize_resources(value: object, *, path: str) -> dict[str, object]:
    request = _coerce_resource_request(value, path=path)
    return {
        "entries": {
            kind: entry.to_dict()
            for kind, entry in cast(ResourceRequest, request).entries.items()
        }
    }


def _plain_adapter_mapping(value: object, *, path: str) -> dict[str, PlainData]:
    return dict(_plain_mapping(value, path=path))


def _plain_adapter_payload(value: object, *, path: str) -> PlainData:
    return cast(PlainData, _plain_mapping({"value": value}, path=path)["value"])


def _object_dict(value: Mapping[str, object]) -> dict[str, object]:
    return {key: item for key, item in value.items()}


def _merge_run_source(target: dict[str, object], source: Mapping[str, object]) -> None:
    for key, value in source.items():
        if key in {"run_uri", "executor", "profile", "dry_run", "notes"}:
            target[key] = value
        elif key == "tags":
            _merge_mapping_field(target, key, cast(Mapping[str, object], value))
        elif key == "selectors":
            _merge_selector_field(target, cast(Mapping[str, object], value))
        elif key == "resume":
            _merge_mapping_members(target, key, cast(Mapping[str, object], value))
        elif key == "execution":
            _merge_execution_field(target, cast(Mapping[str, object], value))
        elif key == "stage_options":
            _merge_stage_options_field(target, cast(Mapping[str, object], value))
        elif key == "environment":
            _merge_environment_field(target, cast(Mapping[str, object], value))
        elif key == "adapter_options":
            _merge_mapping_field(target, key, cast(Mapping[str, object], value))


def _merge_stage_runtime_source(
    target: dict[str, object],
    source: Mapping[str, object],
) -> None:
    for key, value in source.items():
        if key == "resources":
            _merge_resource_field(target, cast(Mapping[str, object], value))
        elif key == "execution":
            _merge_execution_field(target, cast(Mapping[str, object], value))
        elif key == "environment":
            _merge_environment_field(target, cast(Mapping[str, object], value))
        elif key == "adapter_options":
            _merge_mapping_field(target, key, cast(Mapping[str, object], value))


def _merge_mapping_field(
    target: dict[str, object],
    key: str,
    source: Mapping[str, object],
) -> None:
    if not source:
        return
    current = dict(cast(Mapping[str, object], target.get(key, {})))
    current.update(source)
    target[key] = current


def _merge_mapping_members(
    target: dict[str, object],
    key: str,
    source: Mapping[str, object],
) -> None:
    if not source:
        return
    current = dict(cast(Mapping[str, object], target.get(key, {})))
    for member, value in source.items():
        current[member] = value
    target[key] = current


def _merge_selector_field(target: dict[str, object], source: Mapping[str, object]) -> None:
    _merge_mapping_members(target, "selectors", source)


def _merge_execution_field(
    target: dict[str, object],
    source: Mapping[str, object],
) -> None:
    settings = cast(Mapping[str, object], source.get("settings", {}))
    if not settings:
        return
    current = dict(cast(Mapping[str, object], target.get("execution", {})))
    current_settings = dict(cast(Mapping[str, object], current.get("settings", {})))
    current_settings.update(settings)
    current["settings"] = current_settings
    target["execution"] = current


def _merge_environment_field(
    target: dict[str, object],
    source: Mapping[str, object],
) -> None:
    if not source:
        return
    current = dict(cast(Mapping[str, object], target.get("environment", {})))
    if "inherit" in source:
        current["inherit"] = source["inherit"]
    if "set_variables" in source:
        variables = cast(Mapping[str, object], source["set_variables"])
        if variables:
            current_variables = dict(
                cast(Mapping[str, object], current.get("set_variables", {}))
            )
            current_variables.update(variables)
            current["set_variables"] = current_variables
    if "unset_variables" in source:
        current["unset_variables"] = source["unset_variables"]
    target["environment"] = current


def _merge_stage_options_field(
    target: dict[str, object],
    source: Mapping[str, object],
) -> None:
    if not source:
        return
    current = {
        stage_id: dict(cast(Mapping[str, object], stage_options))
        for stage_id, stage_options in cast(
            Mapping[str, object],
            target.get("stage_options", {}),
        ).items()
    }
    for stage_id, stage_source in source.items():
        stage_target = current.get(stage_id, {})
        _merge_stage_runtime_source(
            stage_target,
            cast(Mapping[str, object], stage_source),
        )
        current[stage_id] = stage_target
    target["stage_options"] = current


def _merge_resource_field(
    target: dict[str, object],
    source: Mapping[str, object],
) -> None:
    entries = cast(Mapping[str, object], source.get("entries", {}))
    if not entries:
        return
    current = dict(cast(Mapping[str, object], target.get("resources", {})))
    current_entries = dict(cast(Mapping[str, object], current.get("entries", {})))
    current_entries.update(entries)
    current["entries"] = current_entries
    target["resources"] = current


def _freeze_source_mapping(
    value: Mapping[str, object],
    *,
    path: str,
) -> Mapping[str, PlainData]:
    plain = _plain_mapping(value, path=path)
    return cast(
        Mapping[str, PlainData],
        freeze_plain_data(_sort_plain_mapping(plain), path=path),
    )


def _sort_plain_mapping(value: Mapping[str, PlainData]) -> dict[str, PlainData]:
    return {key: _sort_plain_value(value[key]) for key in sorted(value)}


def _sort_plain_value(value: PlainData) -> PlainData:
    if isinstance(value, dict):
        return _sort_plain_mapping(value)
    if isinstance(value, list):
        return [_sort_plain_value(item) for item in value]
    return value


def _profile_name(value: object, *, path: str) -> str:
    text = _optional_profile_name(value, path=path)
    if text is None:
        raise RuntimeResourceError(f"{path} must be a non-empty string")
    return text


def _optional_profile_name(value: object, *, path: str) -> str | None:
    if value is None:
        return None
    return _optional_string(value, path=path)


__all__ = [
    "RunOptionsSource",
    "RuntimeProfile",
    "RuntimeProfileCollection",
    "merge_run_options",
    "parse_runtime_profile",
    "parse_runtime_profiles",
    "select_runtime_profile",
]
