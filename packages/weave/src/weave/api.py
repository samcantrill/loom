"""Public config composition API."""

from __future__ import annotations

import sys
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

from ._argv import (
    ArgvScopedOverlay,
    ArgvUnparsedArg,
    ArgvValueOverride,
    ParsedConfigArgv,
    ScopedOverlayCandidate,
    ScopedOverlayCandidateOrigin,
    parse_config_argv as _parse_config_argv,
)
from .digests import Fingerprint
from .plain import PlainData, ensure_plain_data, to_plain_data
from .errors import ConfigError, ConfigValidationError

from .artifacts import (
    SCHEMA_VERSION as ARTIFACT_SCHEMA_VERSION,
    CompositionManifest,
    ConfigFingerprintRecord,
    RawSourceSnapshotBundle,
    RawSourceSnapshotPayload,
    RawSourceSnapshotReference,
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
    raw_source_snapshots: RawSourceSnapshotBundle

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
        if not isinstance(self.raw_source_snapshots, RawSourceSnapshotBundle):
            raise ConfigValidationError(
                "ConfigCompositionInspection.raw_source_snapshots must be a RawSourceSnapshotBundle"
            )

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
            raw_source_snapshots=self.raw_source_snapshots,
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
    raw_source_snapshots: RawSourceSnapshotBundle = field(
        default_factory=lambda: RawSourceSnapshotBundle(
            schema_version=ARTIFACT_SCHEMA_VERSION,
            enabled=False,
            payloads=(),
            references=(),
            metadata={"reason": "not_requested_default"},
        )
    )


@dataclass(frozen=True, slots=True)
class ConfigArgvWarning:
    code: str
    message: str
    source_order: int
    token: str
    path: str | None
    remediation: str | None
    details: dict[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.code:
            raise ConfigValidationError("ConfigArgvWarning.code must be non-empty")
        if not self.message:
            raise ConfigValidationError("ConfigArgvWarning.message must be non-empty")
        if self.source_order < -1:
            raise ConfigValidationError("ConfigArgvWarning.source_order must be >= -1")
        if not isinstance(self.token, str):
            raise ConfigValidationError("ConfigArgvWarning.token must be a string")
        if self.path is not None and not isinstance(self.path, str):
            raise ConfigValidationError("ConfigArgvWarning.path must be a string or None")
        if self.remediation is not None and not isinstance(self.remediation, str):
            raise ConfigValidationError("ConfigArgvWarning.remediation must be a string or None")

        try:
            details = ensure_plain_data(self.details, path=f"ConfigArgvWarning[{self.code}].details")
        except Exception as exc:  # noqa: BLE001
            raise ConfigValidationError("ConfigArgvWarning.details must be plain data") from exc
        if not isinstance(details, dict):
            raise ConfigValidationError("ConfigArgvWarning.details must be a mapping")
        object.__setattr__(self, "details", cast(dict[str, PlainData], details))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "code": self.code,
            "message": self.message,
            "source_order": self.source_order,
            "token": self.token,
            "path": self.path,
            "remediation": self.remediation,
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class ConfigArgvCompositionResult:
    command: str
    base_config_path: str
    parsed_argv: ParsedConfigArgv
    value_overrides: tuple[ArgvValueOverride, ...]
    scoped_overlays: tuple[ArgvScopedOverlay, ...]
    unparsed_args: tuple[ArgvUnparsedArg, ...]
    warnings: tuple[ConfigArgvWarning, ...]
    composed_config: ComposedConfig

    def __post_init__(self) -> None:
        _validate_argv_result_common(
            command=self.command,
            base_config_path=self.base_config_path,
            parsed_argv=self.parsed_argv,
            value_overrides=self.value_overrides,
            scoped_overlays=self.scoped_overlays,
            unparsed_args=self.unparsed_args,
            warnings=self.warnings,
        )
        if not isinstance(self.composed_config, ComposedConfig):
            raise ConfigValidationError("ConfigArgvCompositionResult.composed_config must be ComposedConfig")
        object.__setattr__(self, "value_overrides", tuple(self.value_overrides))
        object.__setattr__(self, "scoped_overlays", tuple(self.scoped_overlays))
        object.__setattr__(self, "unparsed_args", tuple(self.unparsed_args))
        object.__setattr__(self, "warnings", tuple(self.warnings))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            **_argv_result_metadata_to_dict(
                command=self.command,
                base_config_path=self.base_config_path,
                parsed_argv=self.parsed_argv,
                value_overrides=self.value_overrides,
                scoped_overlays=self.scoped_overlays,
                unparsed_args=self.unparsed_args,
                warnings=self.warnings,
            ),
            "composed_config": _composed_config_to_dict(self.composed_config),
        }


@dataclass(frozen=True, slots=True)
class ConfigArgvInspectionResult:
    command: str
    base_config_path: str
    parsed_argv: ParsedConfigArgv
    value_overrides: tuple[ArgvValueOverride, ...]
    scoped_overlays: tuple[ArgvScopedOverlay, ...]
    unparsed_args: tuple[ArgvUnparsedArg, ...]
    warnings: tuple[ConfigArgvWarning, ...]
    inspection: ConfigCompositionInspection

    def __post_init__(self) -> None:
        _validate_argv_result_common(
            command=self.command,
            base_config_path=self.base_config_path,
            parsed_argv=self.parsed_argv,
            value_overrides=self.value_overrides,
            scoped_overlays=self.scoped_overlays,
            unparsed_args=self.unparsed_args,
            warnings=self.warnings,
        )
        if not isinstance(self.inspection, ConfigCompositionInspection):
            raise ConfigValidationError("ConfigArgvInspectionResult.inspection must be ConfigCompositionInspection")
        object.__setattr__(self, "value_overrides", tuple(self.value_overrides))
        object.__setattr__(self, "scoped_overlays", tuple(self.scoped_overlays))
        object.__setattr__(self, "unparsed_args", tuple(self.unparsed_args))
        object.__setattr__(self, "warnings", tuple(self.warnings))

    def to_composed_config(self) -> ComposedConfig:
        return self.inspection.to_composed_config()

    def to_dict(self) -> dict[str, PlainData]:
        return {
            **_argv_result_metadata_to_dict(
                command=self.command,
                base_config_path=self.base_config_path,
                parsed_argv=self.parsed_argv,
                value_overrides=self.value_overrides,
                scoped_overlays=self.scoped_overlays,
                unparsed_args=self.unparsed_args,
                warnings=self.warnings,
            ),
            "inspection": _inspection_to_dict(self.inspection),
        }



def compose_config_from_argv(
    argv: Sequence[str] | None = None,
    *,
    command_choices: Collection[str] | None = None,
    allow_unparsed: bool = False,
    recipe_catalog: RecipeCatalog | None = None,
    include_raw_source_snapshots: bool = False,
) -> ConfigArgvCompositionResult:
    inspection_result = inspect_config_from_argv(
        argv=argv,
        command_choices=command_choices,
        allow_unparsed=allow_unparsed,
        recipe_catalog=recipe_catalog,
        include_raw_source_snapshots=include_raw_source_snapshots,
    )
    return ConfigArgvCompositionResult(
        command=inspection_result.command,
        base_config_path=inspection_result.base_config_path,
        parsed_argv=inspection_result.parsed_argv,
        value_overrides=inspection_result.value_overrides,
        scoped_overlays=inspection_result.scoped_overlays,
        unparsed_args=inspection_result.unparsed_args,
        warnings=inspection_result.warnings,
        composed_config=inspection_result.inspection.to_composed_config(),
    )


def inspect_config_from_argv(
    argv: Sequence[str] | None = None,
    *,
    command_choices: Collection[str] | None = None,
    allow_unparsed: bool = False,
    recipe_catalog: RecipeCatalog | None = None,
    include_raw_source_snapshots: bool = False,
) -> ConfigArgvInspectionResult:
    from .compose import _inspect_config_composition_with_argv_scoped_overlays

    if recipe_catalog is not None and not isinstance(recipe_catalog, RecipeCatalog):
        raise ConfigValidationError("recipe_catalog must be a RecipeCatalog")
    if not isinstance(include_raw_source_snapshots, bool):
        raise ConfigValidationError("include_raw_source_snapshots must be a bool")

    catalog = recipe_catalog if recipe_catalog is not None else _get_default_recipe_catalog()
    parsed = _parse_config_argv(
        _normalize_public_argv(argv),
        command_choices=command_choices,
        allow_unparsed=allow_unparsed,
    )
    inspection = _inspect_config_composition_with_argv_scoped_overlays(
        parsed.base_config_path,
        recipe_catalog=catalog,
        argv_scoped_overlays=parsed.scoped_overlays,
        overrides=parsed.override_strings,
        include_raw_source_snapshots=include_raw_source_snapshots,
    )
    warnings = _argv_warnings(parsed=parsed, recipe_catalog=catalog)
    return ConfigArgvInspectionResult(
        command=parsed.command,
        base_config_path=parsed.base_config_path,
        parsed_argv=parsed,
        value_overrides=parsed.value_overrides,
        scoped_overlays=parsed.scoped_overlays,
        unparsed_args=parsed.unparsed_args,
        warnings=warnings,
        inspection=inspection,
    )


def _normalize_public_argv(argv: Sequence[str] | None) -> Sequence[str]:
    if argv is None:
        return tuple(sys.argv[1:])
    return argv


def _argv_warnings(*, parsed: ParsedConfigArgv, recipe_catalog: RecipeCatalog) -> tuple[ConfigArgvWarning, ...]:
    candidates_by_override = {
        override: _warning_candidates(parsed.base_config_path, override)
        for override in parsed.value_overrides
        if override.operation == "update" and isinstance(override.value, str)
    }
    candidates_by_override = {
        override: candidates
        for override, candidates in candidates_by_override.items()
        if any(candidate.exists for candidate in candidates)
    }
    if not candidates_by_override:
        return ()

    try:
        from .compose import _inspect_config_composition_with_argv_scoped_overlays

        pre_override = _inspect_config_composition_with_argv_scoped_overlays(
            parsed.base_config_path,
            recipe_catalog=recipe_catalog,
            argv_scoped_overlays=parsed.scoped_overlays,
            overrides=(),
            include_raw_source_snapshots=False,
        )
    except ConfigError:
        return ()

    warnings: list[ConfigArgvWarning] = []
    for override, candidates in candidates_by_override.items():
        if not isinstance(_lookup_dot_path(pre_override.resolved, override.path), Mapping):
            continue
        existing = [candidate for candidate in candidates if candidate.exists]
        warnings.append(
            ConfigArgvWarning(
                code="possible_missing_scoped_overlay_slash",
                message=(
                    "Value override targets an existing mapping and the RHS resolves like "
                    "a scoped overlay source."
                ),
                source_order=override.order,
                token=override.raw,
                path=override.path,
                remediation="Use trailing-slash scoped overlay syntax, for example 'scope/=variant'.",
                details={
                    "rhs": override.value,
                    "candidate_paths": [candidate.path for candidate in candidates],
                    "resolved_candidate_paths": [candidate.path for candidate in existing],
                },
            )
        )
    return tuple(warnings)


def _warning_candidates(base_config_path: str, override: ArgvValueOverride) -> tuple[ScopedOverlayCandidate, ...]:
    value = override.value
    if not isinstance(value, str) or value == "" or value.startswith("~"):
        return ()
    rhs_path = Path(value)
    if rhs_path.is_absolute():
        path = rhs_path.resolve(strict=False)
        return (ScopedOverlayCandidate(path=str(path), origin="absolute", exists=path.is_file()),)

    base_dir = Path(base_config_path).parent.resolve(strict=False)
    scope_path = tuple(segment for segment in override.path.split(".") if segment)
    if not scope_path:
        return ()
    scope_dir = base_dir.joinpath(*scope_path).resolve(strict=False)
    variants = _warning_rhs_variants(rhs_path)
    candidates: list[ScopedOverlayCandidate] = []
    for origin, root in (("scope_directory", scope_dir), ("base_directory", base_dir)):
        for variant in variants:
            path = (root / variant).resolve(strict=False)
            candidates.append(
                ScopedOverlayCandidate(
                    path=str(path),
                    origin=cast(ScopedOverlayCandidateOrigin, origin),
                    exists=path.is_file(),
                )
            )
    return tuple(candidates)


def _warning_rhs_variants(rhs_path: Path) -> tuple[Path, ...]:
    if rhs_path.suffix:
        return (rhs_path,)
    try:
        return (rhs_path.with_suffix(".yaml"), rhs_path.with_suffix(".yml"))
    except ValueError:
        return (rhs_path,)


def _lookup_dot_path(mapping: Mapping[str, PlainData], path: str) -> PlainData | None:
    current: PlainData | None = cast(PlainData, mapping)
    for segment in path.split("."):
        if not isinstance(current, Mapping) or segment not in current:
            return None
        current = current[segment]
    return current


def _validate_argv_result_common(
    *,
    command: str,
    base_config_path: str,
    parsed_argv: ParsedConfigArgv,
    value_overrides: tuple[ArgvValueOverride, ...],
    scoped_overlays: tuple[ArgvScopedOverlay, ...],
    unparsed_args: tuple[ArgvUnparsedArg, ...],
    warnings: tuple[ConfigArgvWarning, ...],
) -> None:
    if command == "":
        raise ConfigValidationError("argv result command must be non-empty")
    if base_config_path == "":
        raise ConfigValidationError("argv result base_config_path must be non-empty")
    if not isinstance(parsed_argv, ParsedConfigArgv):
        raise ConfigValidationError("parsed_argv must be ParsedConfigArgv")
    if command != parsed_argv.command or base_config_path != parsed_argv.base_config_path:
        raise ConfigValidationError("argv result metadata must match parsed_argv")
    if tuple(value_overrides) != parsed_argv.value_overrides:
        raise ConfigValidationError("value_overrides must mirror parsed_argv.value_overrides")
    if tuple(scoped_overlays) != parsed_argv.scoped_overlays:
        raise ConfigValidationError("scoped_overlays must mirror parsed_argv.scoped_overlays")
    if tuple(unparsed_args) != parsed_argv.unparsed_args:
        raise ConfigValidationError("unparsed_args must mirror parsed_argv.unparsed_args")
    for index, warning in enumerate(tuple(warnings)):
        if not isinstance(warning, ConfigArgvWarning):
            raise ConfigValidationError(f"warnings[{index}] must be ConfigArgvWarning")


def _argv_result_metadata_to_dict(
    *,
    command: str,
    base_config_path: str,
    parsed_argv: ParsedConfigArgv,
    value_overrides: tuple[ArgvValueOverride, ...],
    scoped_overlays: tuple[ArgvScopedOverlay, ...],
    unparsed_args: tuple[ArgvUnparsedArg, ...],
    warnings: tuple[ConfigArgvWarning, ...],
) -> dict[str, PlainData]:
    return {
        "command": command,
        "base_config_path": base_config_path,
        "parsed_argv": parsed_argv.to_dict(),
        "value_overrides": [override.to_dict() for override in value_overrides],
        "scoped_overlays": [overlay.to_dict() for overlay in scoped_overlays],
        "unparsed_args": [arg.to_dict() for arg in unparsed_args],
        "warnings": [warning.to_dict() for warning in warnings],
    }


def _composed_config_to_dict(config: ComposedConfig) -> dict[str, PlainData]:
    return {
        "resolved": config.resolved,
        "redacted": config.redacted,
        "unresolved": config.unresolved,
        "provenance": config.provenance.to_dict(),
        "recipe_manifest": list(config.recipe_manifest),
        "fingerprint": config.fingerprint,
        "manifest": config.manifest.to_dict(),
        "source_artifacts": [record.to_dict() for record in config.source_artifacts],
        "fingerprint_records": [record.to_dict() for record in config.fingerprint_records],
        "raw_source_snapshots": config.raw_source_snapshots.to_dict(),
    }


def _inspection_to_dict(inspection: ConfigCompositionInspection) -> dict[str, PlainData]:
    return {
        "stages": [
            {"name": stage.name, "status": stage.status, "payload": stage.payload}
            for stage in inspection.stages
        ],
        "unresolved": inspection.unresolved,
        "resolved": inspection.resolved,
        "redacted": inspection.redacted,
        "provenance": inspection.provenance.to_dict(),
        "recipe_manifest": list(inspection.recipe_manifest),
        "fingerprint": inspection.fingerprint,
        "manifest": inspection.manifest.to_dict(),
        "source_artifacts": [record.to_dict() for record in inspection.source_artifacts],
        "fingerprint_records": [record.to_dict() for record in inspection.fingerprint_records],
        "raw_source_snapshots": inspection.raw_source_snapshots.to_dict(),
    }


def compose_config(
    config_path: str | Path,
    overlays: list[str | Path] | tuple[str | Path, ...] = (),
    overrides: list[str] | tuple[str, ...] = (),
    recipe_catalog: RecipeCatalog | None = None,
    *,
    include_raw_source_snapshots: bool = False,
) -> ComposedConfig:
    from .compose import inspect_config_composition

    if overlays is None:
        raise ConfigValidationError("overlays may not be None")
    if overrides is None:
        raise ConfigValidationError("overrides may not be None")
    if recipe_catalog is not None and not isinstance(recipe_catalog, RecipeCatalog):
        raise ConfigValidationError("recipe_catalog must be a RecipeCatalog")
    if not isinstance(include_raw_source_snapshots, bool):
        raise ConfigValidationError("include_raw_source_snapshots must be a bool")

    return inspect_config_composition(
        config_path=config_path,
        overlays=tuple(overlays),
        overrides=tuple(overrides),
        recipe_catalog=recipe_catalog if recipe_catalog is not None else _get_default_recipe_catalog(),
        include_raw_source_snapshots=include_raw_source_snapshots,
    ).to_composed_config()


def inspect_config_composition(
    config_path: str | Path,
    overlays: list[str | Path] | tuple[str | Path, ...] = (),
    overrides: list[str] | tuple[str, ...] = (),
    recipe_catalog: RecipeCatalog | None = None,
    *,
    include_raw_source_snapshots: bool = False,
) -> ConfigCompositionInspection:
    from .compose import inspect_config_composition as _inspect_config_composition

    if overlays is None:
        raise ConfigValidationError("overlays may not be None")
    if overrides is None:
        raise ConfigValidationError("overrides may not be None")
    if recipe_catalog is not None and not isinstance(recipe_catalog, RecipeCatalog):
        raise ConfigValidationError("recipe_catalog must be a RecipeCatalog")
    if not isinstance(include_raw_source_snapshots, bool):
        raise ConfigValidationError("include_raw_source_snapshots must be a bool")

    return _inspect_config_composition(
        config_path=config_path,
        overlays=tuple(overlays),
        overrides=tuple(overrides),
        recipe_catalog=recipe_catalog if recipe_catalog is not None else _get_default_recipe_catalog(),
        include_raw_source_snapshots=include_raw_source_snapshots,
    )


def compose_config_with_catalog(
    config_path: str | Path,
    *,
    recipe_catalog: RecipeCatalog,
    overlays: list[str | Path] | tuple[str | Path, ...] = (),
    overrides: list[str] | tuple[str, ...] = (),
    include_raw_source_snapshots: bool = False,
) -> ComposedConfig:
    from .compose import inspect_config_composition

    if not isinstance(recipe_catalog, RecipeCatalog):
        raise ConfigValidationError("recipe_catalog must be a RecipeCatalog")
    if overlays is None:
        raise ConfigValidationError("overlays may not be None")
    if overrides is None:
        raise ConfigValidationError("overrides may not be None")
    if not isinstance(include_raw_source_snapshots, bool):
        raise ConfigValidationError("include_raw_source_snapshots must be a bool")

    return inspect_config_composition(
        config_path=config_path,
        overlays=tuple(overlays),
        overrides=tuple(overrides),
        recipe_catalog=recipe_catalog,
        include_raw_source_snapshots=include_raw_source_snapshots,
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
    "ArgvScopedOverlay",
    "ArgvUnparsedArg",
    "ArgvValueOverride",
    "ComposedConfig",
    "ConfigArgvCompositionResult",
    "ConfigArgvInspectionResult",
    "ConfigArgvWarning",
    "ConfigCompositionInspection",
    "ConfigCompositionStageRecord",
    "ParsedConfigArgv",
    "ScopedOverlayCandidate",
    "compose_config",
    "compose_config_from_argv",
    "inspect_config_composition",
    "inspect_config_from_argv",
    "compose_config_with_catalog",
    "compare_config_artifact_fingerprints",
    "ConfigFingerprintComparison",
    "RawSourceSnapshotBundle",
    "RawSourceSnapshotPayload",
    "RawSourceSnapshotReference",
    "ARTIFACT_SAFE_FINGERPRINT_LABEL",
    "ARTIFACT_SAFE_FINGERPRINT_POLICY",
    "ARTIFACT_SAFE_RUNTIME_REPLAY",
    "instantiate",
    "register_recipe",
]
