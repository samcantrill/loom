"""Config composition orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from loom.fingerprints import Fingerprint, hash_mapping

from .api import ComposedConfig
from .errors import ConfigValidationError, UnsupportedRecipeError
from .interpolation import resolve_interpolation
from .load import load_config
from .merge import merge_configs
from .overrides import apply_overrides, parse_overrides
from .provenance import SCHEMA_VERSION, ConfigProvenance, ParsedOverride, ConfigSource, build_config_fingerprint
from .redaction import redact_secrets
from .validation import validate_no_recipe_keys, validate_top_level_fields


def compose_config(
    config_path: str | Path,
    overlays: Sequence[str | Path] = (),
    overrides: Sequence[str] = (),
    recipe_catalog: object | None = None,
) -> ComposedConfig:
    if recipe_catalog is not None:
        raise UnsupportedRecipeError("recipe_catalog is not supported until Phase 5")
    if overlays is None:
        raise ConfigValidationError("overlays may not be None")
    if overrides is None:
        raise ConfigValidationError("overrides may not be None")

    base_config, base_source = load_config(config_path, kind="base", order=0)
    sources = [base_source]

    merged = base_config
    for order, overlay_path in enumerate(overlays, start=1):
        overlay_config, overlay_source = load_config(overlay_path, kind="overlay", order=order)
        sources.append(overlay_source)
        merged = merge_configs(merged, overlay_config, path=f"overlay[{order}]")

    parsed_overrides = parse_overrides(overrides)
    merged = apply_overrides(merged, parsed_overrides)

    resolved = resolve_interpolation(merged)
    validate_no_recipe_keys(resolved)
    validated = validate_top_level_fields(resolved)
    redacted = redact_secrets(validated)

    resolved_fingerprint = hash_mapping(validated)
    provenance = _build_provenance(
        config_path=str(base_source.path),
        sources=tuple(sources),
        overrides=parsed_overrides,
        resolved_fingerprint=resolved_fingerprint,
    )
    fingerprint = build_config_fingerprint(
        resolved=validated,
        sources=provenance.sources,
        overrides=provenance.overrides,
        schema_version=provenance.schema_version,
    )

    return ComposedConfig(
        resolved=validated,
        redacted=redacted,
        provenance=provenance,
        recipe_manifest=(),
        fingerprint=fingerprint,
    )


def _build_provenance(
    *,
    config_path: str,
    sources: tuple[ConfigSource, ...],
    overrides: tuple[ParsedOverride, ...],
    resolved_fingerprint: Fingerprint,
) -> ConfigProvenance:
    return ConfigProvenance(
        schema_version=SCHEMA_VERSION,
        config_path=config_path,
        sources=tuple(sources),
        overrides=overrides,
        resolved_fingerprint=resolved_fingerprint,
        recipe_manifest_count=0,
        metadata={},
    )
