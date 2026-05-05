"""Public config composition API."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Mapping, cast

from loom.fingerprints import Fingerprint
from loom.serialization import PlainData, ensure_plain_data, to_plain_data
from loom.config.errors import ConfigValidationError

from .artifacts import (
    SCHEMA_VERSION as ARTIFACT_SCHEMA_VERSION,
    CompositionManifest,
    ConfigFingerprintRecord,
    SourceArtifactRecord,
)
from .fingerprints import (
    ARTIFACT_SAFE_FINGERPRINT_LABEL,
    ARTIFACT_SAFE_FINGERPRINT_POLICY,
    ARTIFACT_SAFE_RUNTIME_REPLAY,
    ConfigFingerprintComparison,
    compare_config_artifact_fingerprints,
)
from .provenance import ConfigProvenance
from .recipes import RecipeCatalog, RecipeImplementation


__default_recipe_catalog: RecipeCatalog | None = None


@dataclass(frozen=True, slots=True)
class ConfigCompositionStageRecord:
    name: str
    status: Literal["completed", "skipped", "failed"]
    payload: dict[str, PlainData]

    def __post_init__(self) -> None:
        if self.name == "":
            raise ConfigValidationError("ConfigCompositionStageRecord.name must be non-empty")
        if self.status not in {"completed", "skipped", "failed"}:
            raise ConfigValidationError(f"Unsupported stage status: {self.status!r}")

        try:
            payload = to_plain_data(self.payload, path=f"ConfigCompositionStageRecord[{self.name}].payload")
        except Exception as exc:  # noqa: BLE001
            raise ConfigValidationError("stage payload must be plain data") from exc

        if not isinstance(payload, dict):
            raise ConfigValidationError("ConfigCompositionStageRecord.payload must be a mapping")
        object.__setattr__(self, "payload", cast(dict[str, PlainData], payload))


@dataclass(frozen=True, slots=True)
class ConfigCompositionInspection:
    stages: tuple[ConfigCompositionStageRecord, ...]
    unresolved: dict[str, PlainData]
    resolved: dict[str, PlainData]
    redacted: dict[str, PlainData]
    provenance: ConfigProvenance
    recipe_manifest: tuple[dict[str, PlainData], ...]
    fingerprint: Fingerprint
    manifest: CompositionManifest
    source_artifacts: tuple[SourceArtifactRecord, ...]
    fingerprint_records: tuple[ConfigFingerprintRecord, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.stages, tuple):
            raise ConfigValidationError("ConfigCompositionInspection.stages must be a tuple")

        plain_unresolved = ensure_plain_data(self.unresolved, path="ConfigCompositionInspection.unresolved")
        plain_resolved = ensure_plain_data(self.resolved, path="ConfigCompositionInspection.resolved")
        plain_redacted = ensure_plain_data(self.redacted, path="ConfigCompositionInspection.redacted")

        if not isinstance(plain_unresolved, dict):
            raise ConfigValidationError("ConfigCompositionInspection.unresolved must be a mapping")
        if not isinstance(plain_resolved, dict):
            raise ConfigValidationError("ConfigCompositionInspection.resolved must be a mapping")
        if not isinstance(plain_redacted, dict):
            raise ConfigValidationError("ConfigCompositionInspection.redacted must be a mapping")

        normalized_manifest = tuple(self.recipe_manifest)
        if not isinstance(normalized_manifest, tuple):
            raise ConfigValidationError("ConfigCompositionInspection.recipe_manifest must be a tuple")

        for index, item in enumerate(normalized_manifest):
            if not isinstance(item, dict):
                raise ConfigValidationError(f"recipe_manifest[{index}] must be a mapping")
            ensure_plain_data(item, path=f"ConfigCompositionInspection.recipe_manifest[{index}]")

        if not isinstance(self.source_artifacts, tuple):
            raise ConfigValidationError("ConfigCompositionInspection.source_artifacts must be a tuple")
        if not isinstance(self.fingerprint_records, tuple):
            raise ConfigValidationError("ConfigCompositionInspection.fingerprint_records must be a tuple")

        for index, source_artifact in enumerate(self.source_artifacts):
            if not isinstance(source_artifact, SourceArtifactRecord):
                raise ConfigValidationError(
                    f"source_artifacts[{index}] must be SourceArtifactRecord"
                )

        for index, fingerprint_record in enumerate(self.fingerprint_records):
            if not isinstance(fingerprint_record, ConfigFingerprintRecord):
                raise ConfigValidationError(
                    f"fingerprint_records[{index}] must be ConfigFingerprintRecord"
                )

        object.__setattr__(self, "unresolved", cast(dict[str, PlainData], plain_unresolved))
        object.__setattr__(self, "resolved", cast(dict[str, PlainData], plain_resolved))
        object.__setattr__(self, "redacted", cast(dict[str, PlainData], plain_redacted))
        object.__setattr__(self, "recipe_manifest", normalized_manifest)

    def stage(self, name: str) -> ConfigCompositionStageRecord | None:
        for item in self.stages:
            if item.name == name:
                return item
        return None

    def to_composed_config(self) -> "ComposedConfig":
        return ComposedConfig(
            resolved=self.resolved,
            redacted=self.redacted,
            provenance=self.provenance,
            recipe_manifest=self.recipe_manifest,
            fingerprint=self.fingerprint,
            unresolved=self.unresolved,
            manifest=self.manifest,
            source_artifacts=self.source_artifacts,
            fingerprint_records=self.fingerprint_records,
        )


@dataclass(frozen=True, slots=True)
class ComposedConfig:
    resolved: dict[str, PlainData]
    redacted: dict[str, PlainData]
    provenance: ConfigProvenance
    recipe_manifest: tuple[dict[str, PlainData], ...]
    fingerprint: Fingerprint
    unresolved: dict[str, PlainData] = field(default_factory=dict)
    manifest: CompositionManifest = field(
        default_factory=lambda: CompositionManifest(
            schema_version=ARTIFACT_SCHEMA_VERSION,
            source_artifacts=(),
            fingerprint_records=(),
            recipe_manifest=(),
            metadata={},
        )
    )
    source_artifacts: tuple[SourceArtifactRecord, ...] = ()
    fingerprint_records: tuple[ConfigFingerprintRecord, ...] = ()


def compose_config(
    config_path: str | Path,
    overlays: list[str | Path] | tuple[str | Path, ...] = (),
    overrides: list[str] | tuple[str, ...] = (),
    recipe_catalog: RecipeCatalog | None = None,
) -> ComposedConfig:
    from .compose import inspect_config_composition

    if overlays is None:
        raise ConfigValidationError("overlays may not be None")
    if overrides is None:
        raise ConfigValidationError("overrides may not be None")
    if recipe_catalog is not None and not isinstance(recipe_catalog, RecipeCatalog):
        raise ConfigValidationError("recipe_catalog must be a RecipeCatalog")

    return inspect_config_composition(
        config_path=config_path,
        overlays=tuple(overlays),
        overrides=tuple(overrides),
        recipe_catalog=recipe_catalog if recipe_catalog is not None else _get_default_recipe_catalog(),
    ).to_composed_config()


def inspect_config_composition(
    config_path: str | Path,
    overlays: list[str | Path] | tuple[str | Path, ...] = (),
    overrides: list[str] | tuple[str, ...] = (),
    recipe_catalog: RecipeCatalog | None = None,
) -> ConfigCompositionInspection:
    from .compose import inspect_config_composition as _inspect_config_composition

    if overlays is None:
        raise ConfigValidationError("overlays may not be None")
    if overrides is None:
        raise ConfigValidationError("overrides may not be None")
    if recipe_catalog is not None and not isinstance(recipe_catalog, RecipeCatalog):
        raise ConfigValidationError("recipe_catalog must be a RecipeCatalog")

    return _inspect_config_composition(
        config_path=config_path,
        overlays=tuple(overlays),
        overrides=tuple(overrides),
        recipe_catalog=recipe_catalog if recipe_catalog is not None else _get_default_recipe_catalog(),
    )


def compose_config_with_catalog(
    config_path: str | Path,
    *,
    recipe_catalog: RecipeCatalog,
    overlays: list[str | Path] | tuple[str | Path, ...] = (),
    overrides: list[str] | tuple[str, ...] = (),
) -> ComposedConfig:
    from .compose import inspect_config_composition

    if not isinstance(recipe_catalog, RecipeCatalog):
        raise ConfigValidationError("recipe_catalog must be a RecipeCatalog")
    if overlays is None:
        raise ConfigValidationError("overlays may not be None")
    if overrides is None:
        raise ConfigValidationError("overrides may not be None")

    return inspect_config_composition(
        config_path=config_path,
        overlays=tuple(overlays),
        overrides=tuple(overrides),
        recipe_catalog=recipe_catalog,
    ).to_composed_config()


def instantiate(value: object, *, runtime: Mapping[str, object] | None = None) -> object:
    from .instantiate.recursive import instantiate as _instantiate

    return _instantiate(value=value, runtime=runtime)


def register_recipe(name: str, recipe: RecipeImplementation, *, replace: bool = False) -> None:
    _get_default_recipe_catalog().register(name=name, recipe=recipe, replace=replace)


def _get_default_recipe_catalog() -> RecipeCatalog:
    global __default_recipe_catalog
    if __default_recipe_catalog is None:
        __default_recipe_catalog = RecipeCatalog()
    return __default_recipe_catalog


__all__ = [
    "ComposedConfig",
    "ConfigCompositionInspection",
    "ConfigCompositionStageRecord",
    "compose_config",
    "inspect_config_composition",
    "compose_config_with_catalog",
    "compare_config_artifact_fingerprints",
    "ConfigFingerprintComparison",
    "ARTIFACT_SAFE_FINGERPRINT_LABEL",
    "ARTIFACT_SAFE_FINGERPRINT_POLICY",
    "ARTIFACT_SAFE_RUNTIME_REPLAY",
    "instantiate",
    "register_recipe",
]
