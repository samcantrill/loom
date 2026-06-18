"""Runtime option extraction from composed config mappings."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

from loom.pipeline.errors import RuntimeResourceError
from loom.pipeline.runtime.options import RunOptions
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

    def __post_init__(self) -> None:
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
                else parse_runtime_profiles(self.profiles)
            ),
        )

    def merge(
        self,
        *,
        explicit: RunOptionsSource | None = None,
        profile: str | None = None,
        known_stage_ids: Iterable[str] | None = None,
    ) -> RunOptions:
        """Merge config runtime sections with an explicit runtime source."""

        return merge_run_options(
            base=cast(Mapping[str, object], self.options),
            profiles=cast(RuntimeProfileCollection, self.profiles),
            explicit=explicit,
            profile=profile,
            known_stage_ids=known_stage_ids,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            RUNTIME_CONFIG_SECTION: dict(self.options),
            RUNTIME_PROFILES_CONFIG_SECTION: cast(
                RuntimeProfileCollection,
                self.profiles,
            ).to_dict(),
        }


def parse_runtime_config_sections(config: Mapping[str, object]) -> RuntimeConfigSections:
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
    )


def merge_config_run_options(
    config: Mapping[str, object],
    *,
    explicit: RunOptionsSource | None = None,
    profile: str | None = None,
    known_stage_ids: Iterable[str] | None = None,
) -> RunOptions:
    """Merge config-authored runtime options with explicit runtime options."""

    return parse_runtime_config_sections(config).merge(
        explicit=explicit,
        profile=profile,
        known_stage_ids=known_stage_ids,
    )


def _object_mapping(value: object, *, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RuntimeResourceError(f"{path} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise RuntimeResourceError(f"{path} must be a mapping with string keys")
    return cast(Mapping[str, object], value)


__all__ = [
    "RUNTIME_CONFIG_SECTION",
    "RUNTIME_PROFILES_CONFIG_SECTION",
    "RuntimeConfigSections",
    "merge_config_run_options",
    "parse_runtime_config_sections",
]
