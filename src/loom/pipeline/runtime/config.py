"""Runtime option extraction from composed config mappings."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import InitVar, dataclass, field
from types import MappingProxyType
from typing import cast

from loom.pipeline.errors import RuntimeResourceError
from loom.pipeline.resources import ResourceValidatorRegistry
from loom.pipeline.runtime.options import RunOptions, RunStoreOptions
from loom.pipeline.runtime.profiles import (
    RunOptionsSource,
    RuntimeProfileCollection,
    merge_run_options,
    parse_runtime_profiles,
)

RUNTIME_CONFIG_SECTION = "runtime"
RUNTIME_PROFILES_CONFIG_SECTION = "runtime_profiles"


@dataclass(frozen=True, slots=True)
class RuntimeConfigSections:
    """Top-level runtime sections extracted from a resolved config mapping."""

    options: Mapping[str, object] = field(default_factory=dict)
    profiles: RuntimeProfileCollection | Mapping[str, object] | None = None
    validator_registry: InitVar[ResourceValidatorRegistry | None] = None

    def __post_init__(
        self, validator_registry: ResourceValidatorRegistry | None
    ) -> None:
        object.__setattr__(
            self,
            "options",
            MappingProxyType(
                dict(
                    sorted(
                        _object_mapping(
                            self.options,
                            path=RUNTIME_CONFIG_SECTION,
                        ).items()
                    )
                )
            ),
        )
        object.__setattr__(
            self,
            "profiles",
            (
                self.profiles
                if isinstance(self.profiles, RuntimeProfileCollection)
                else parse_runtime_profiles(self.profiles, registry=validator_registry)
            ),
        )

    def merge(
        self,
        *,
        explicit: RunOptionsSource | None = None,
        profile: str | None = None,
        known_stage_ids: Iterable[str] | None = None,
        registry: ResourceValidatorRegistry | None = None,
    ) -> RunOptions:
        """Merge config runtime sections with an explicit runtime source."""

        return merge_run_options(
            base=cast(Mapping[str, object], self.options),
            profiles=cast(RuntimeProfileCollection, self.profiles),
            explicit=explicit,
            profile=profile,
            known_stage_ids=known_stage_ids,
            registry=registry,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            RUNTIME_CONFIG_SECTION: dict(self.options),
            RUNTIME_PROFILES_CONFIG_SECTION: cast(
                RuntimeProfileCollection,
                self.profiles,
            ).to_dict(),
        }


def parse_runtime_config_sections(
    config: Mapping[str, object],
    *,
    registry: ResourceValidatorRegistry | None = None,
) -> RuntimeConfigSections:
    """Extract optional top-level runtime sections from a resolved config."""

    mapping = _object_mapping(config, path="config")
    options = mapping.get(RUNTIME_CONFIG_SECTION, {})
    profiles = mapping.get(RUNTIME_PROFILES_CONFIG_SECTION)
    if options is None:
        options = {}
    return RuntimeConfigSections(
        options=_object_mapping(options, path=f"$.{RUNTIME_CONFIG_SECTION}"),
        profiles=cast(
            RuntimeProfileCollection | Mapping[str, object] | None,
            profiles,
        ),
        validator_registry=registry,
    )


def merge_config_run_options(
    config: Mapping[str, object],
    *,
    explicit: RunOptionsSource | None = None,
    profile: str | None = None,
    known_stage_ids: Iterable[str] | None = None,
    registry: ResourceValidatorRegistry | None = None,
) -> RunOptions:
    """Merge config-authored runtime options with explicit runtime options."""

    return parse_runtime_config_sections(config, registry=registry).merge(
        explicit=explicit,
        profile=profile,
        known_stage_ids=known_stage_ids,
        registry=registry,
    )


def bootstrap_config_run_store_options(
    config: Mapping[str, object], *, profile: str | None = None
) -> RunStoreOptions | None:
    """Select only the run-store option needed before plugin loading.

    The CLI uses this narrow projection to open a resume store before it can
    validate persisted plugin activation evidence. Full runtime validation still
    owns the final option merge; callers must compare this result with it.
    """

    mapping = _object_mapping(config, path="config")
    runtime_value = mapping.get(RUNTIME_CONFIG_SECTION, {})
    if runtime_value is None:
        runtime_value = {}
    runtime = _object_mapping(runtime_value, path=f"$.{RUNTIME_CONFIG_SECTION}")

    selected_profile = profile
    if selected_profile is None and "profile" in runtime:
        selected_profile = _profile_name(
            runtime["profile"], path=f"$.{RUNTIME_CONFIG_SECTION}.profile"
        )

    selected = runtime.get("run_store")
    if selected_profile is not None:
        profiles_value = mapping.get(RUNTIME_PROFILES_CONFIG_SECTION)
        if profiles_value is None:
            raise RuntimeResourceError(
                f"runtime profile {selected_profile!r} was selected but no runtime profiles were supplied"
            )
        profiles = _object_mapping(
            profiles_value, path=f"$.{RUNTIME_PROFILES_CONFIG_SECTION}"
        )
        profile_value = profiles.get(selected_profile)
        if profile_value is None:
            raise RuntimeResourceError(
                f"runtime profile {selected_profile!r} is not defined"
            )
        selected_profile_options = _object_mapping(
            profile_value,
            path=f"$.{RUNTIME_PROFILES_CONFIG_SECTION}[{selected_profile!r}]",
        )
        if "run_store" in selected_profile_options:
            selected = selected_profile_options["run_store"]

    if selected is None:
        return None
    return RunStoreOptions.from_dict(selected)


def _object_mapping(value: object, *, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RuntimeResourceError(f"{path} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise RuntimeResourceError(f"{path} must be a mapping with string keys")
    return cast(Mapping[str, object], value)


def _profile_name(value: object, *, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeResourceError(f"{path} must be a non-empty string")
    return value


__all__ = [
    "RUNTIME_CONFIG_SECTION",
    "RUNTIME_PROFILES_CONFIG_SECTION",
    "RuntimeConfigSections",
    "bootstrap_config_run_store_options",
    "merge_config_run_options",
    "parse_runtime_config_sections",
]
