"""Standalone config composition package."""

from __future__ import annotations

import sys
from types import ModuleType
from typing import TYPE_CHECKING, Final

from .__version__ import __version__
from .errors import ConfigError

if TYPE_CHECKING:
    from .api import (
        ARTIFACT_SAFE_FINGERPRINT_LABEL,
        ARTIFACT_SAFE_FINGERPRINT_POLICY,
        ARTIFACT_SAFE_RUNTIME_REPLAY,
        ComposedConfig,
        ConfigCompositionInspection,
        ConfigCompositionStageRecord,
        ConfigFingerprintComparison,
        RawSourceSnapshotBundle,
        RawSourceSnapshotPayload,
        RawSourceSnapshotReference,
        compare_config_artifact_fingerprints,
        compose_config,
        compose_config_from_argv,
        compose_config_with_catalog,
        inspect_config_composition,
        instantiate,
        register_recipe,
    )
    from .recipes import Recipe, RecipeCatalog
    from .target_checks import TargetCheckResult, check_config_targets


_RESOLVED_SYMBOLS: dict[str, object] = {
    "__version__": __version__,
    "ConfigError": ConfigError,
}
_OPTIONAL_SYMBOLS: Final = frozenset(
    {
        "ComposedConfig",
        "ConfigCompositionInspection",
        "ConfigCompositionStageRecord",
        "inspect_config_composition",
        "compose_config",
        "compose_config_from_argv",
        "compose_config_with_catalog",
        "compare_config_artifact_fingerprints",
        "ConfigFingerprintComparison",
        "RawSourceSnapshotBundle",
        "RawSourceSnapshotPayload",
        "RawSourceSnapshotReference",
        "ARTIFACT_SAFE_FINGERPRINT_LABEL",
        "ARTIFACT_SAFE_FINGERPRINT_POLICY",
        "ARTIFACT_SAFE_RUNTIME_REPLAY",
        "register_recipe",
        "Recipe",
        "RecipeCatalog",
        "instantiate",
        "check_config_targets",
        "TargetCheckResult",
    }
)


def _resolve_optional_symbol(name: str) -> object:
    match name:
        case "instantiate":
            from .instantiate.recursive import instantiate as _instantiate

            return _instantiate
        case "check_config_targets" | "TargetCheckResult":
            from . import target_checks

            return getattr(target_checks, name)
        case (
            "ComposedConfig"
            | "ConfigCompositionInspection"
            | "ConfigCompositionStageRecord"
            | "compose_config"
            | "compose_config_from_argv"
            | "compose_config_with_catalog"
            | "inspect_config_composition"
            | "register_recipe"
        ):
            from . import api

            return getattr(api, name)
        case (
            "compare_config_artifact_fingerprints"
            | "ConfigFingerprintComparison"
            | "RawSourceSnapshotBundle"
            | "RawSourceSnapshotPayload"
            | "RawSourceSnapshotReference"
            | "ARTIFACT_SAFE_FINGERPRINT_LABEL"
            | "ARTIFACT_SAFE_FINGERPRINT_POLICY"
            | "ARTIFACT_SAFE_RUNTIME_REPLAY"
        ):
            from . import api

            return getattr(api, name)
        case "Recipe" | "RecipeCatalog":
            from . import recipes

            return getattr(recipes, name)
    raise AssertionError(f"unexpected config symbol name: {name!r}")


class _WeavePackage(ModuleType):
    def __getattr__(self, name: str) -> object:
        if name in _RESOLVED_SYMBOLS:
            return _RESOLVED_SYMBOLS[name]
        if name not in _OPTIONAL_SYMBOLS:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

        value = _resolve_optional_symbol(name)
        _RESOLVED_SYMBOLS[name] = value
        setattr(self, name, value)
        return value

    def __setattr__(self, name: str, value: object) -> None:
        if name == "instantiate" and isinstance(value, ModuleType):
            value = _resolve_optional_symbol("instantiate")
        super().__setattr__(name, value)

    def __dir__(self) -> list[str]:
        return sorted(__all__)


_module = sys.modules[__name__]
if not isinstance(_module, _WeavePackage):
    _module.__class__ = _WeavePackage

__all__ = [
    "__version__",
    "ConfigError",
    "ComposedConfig",
    "ConfigCompositionInspection",
    "ConfigCompositionStageRecord",
    "inspect_config_composition",
    "compose_config_with_catalog",
    "compare_config_artifact_fingerprints",
    "ConfigFingerprintComparison",
    "RawSourceSnapshotBundle",
    "RawSourceSnapshotPayload",
    "RawSourceSnapshotReference",
    "ARTIFACT_SAFE_FINGERPRINT_LABEL",
    "ARTIFACT_SAFE_FINGERPRINT_POLICY",
    "ARTIFACT_SAFE_RUNTIME_REPLAY",
    "Recipe",
    "RecipeCatalog",
    "compose_config",
    "compose_config_from_argv",
    "instantiate",
    "check_config_targets",
    "TargetCheckResult",
    "register_recipe",
]
