"""Config composition orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from loom.fingerprints import Fingerprint
from loom.serialization import PlainData

from .api import ComposedConfig
from .errors import ConfigValidationError
from .interpolation import resolve_interpolation
from .load import load_config
from .includes import expand_config_includes
from .source_maps import compose_config_with_sources
from .overrides import apply_overrides, parse_overrides
from .provenance import (
    SCHEMA_VERSION,
    ConfigProvenance,
    ParsedOverride,
    ConfigSource,
    build_config_fingerprint,
)
from .redaction import redact_secrets
from .recipes import RecipeCatalog
from .recipes.expansion import expand_recipes, resolve_recipe_argument_interpolation
from .validation import validate_top_level_fields


def compose_config(
    config_path: str | Path,
    *,
    recipe_catalog: RecipeCatalog,
    overlays: Sequence[str | Path] = (),
    overrides: Sequence[str] = (),
) -> ComposedConfig:
    if not isinstance(recipe_catalog, RecipeCatalog):
        raise ConfigValidationError("recipe_catalog must be a RecipeCatalog")

    if overlays is None:
        raise ConfigValidationError("overlays may not be None")
    if overrides is None:
        raise ConfigValidationError("overrides may not be None")

    base_config, base_source = load_config(config_path, kind="base", order=0)
    sources = [base_source]

    overlay_pairs: list[tuple[dict[str, PlainData], ConfigSource]] = []
    for order, overlay_path in enumerate(overlays, start=1):
        overlay_config, overlay_source = load_config(overlay_path, kind="overlay", order=order)
        sources.append(overlay_source)
        overlay_pairs.append((overlay_config, overlay_source))

    merged_with_sources = compose_config_with_sources(
        base_config=base_config,
        base_source=base_source,
        overlays=overlay_pairs,
    )
    merged = merged_with_sources.config
    merged = expand_config_includes(
        merged,
        source_map=merged_with_sources.source_map,
        replacement_sites=merged_with_sources.replacement_sites,
        mapping_sites=merged_with_sources.mapping_sites,
    ).config

    parsed_overrides = parse_overrides(overrides)
    merged = apply_overrides(merged, parsed_overrides)

    resolved_recipe_args = resolve_recipe_argument_interpolation(merged, path="$")
    expanded, recipe_manifest = expand_recipes(resolved_recipe_args, catalog=recipe_catalog, path="$")
    resolved = resolve_interpolation(expanded, path="$")

    validated = validate_top_level_fields(resolved)
    redacted = redact_secrets(validated)

    resolved_fingerprint = build_resolved_fingerprint(validated)
    provenance = _build_provenance(
        config_path=str(base_source.path),
        sources=tuple(sources),
        overrides=parsed_overrides,
        resolved_fingerprint=resolved_fingerprint,
        recipe_manifest_count=len(recipe_manifest),
    )
    fingerprint = build_config_fingerprint(
        resolved=validated,
        sources=provenance.sources,
        overrides=provenance.overrides,
        recipe_manifest=recipe_manifest,
        schema_version=provenance.schema_version,
    )

    return ComposedConfig(
        resolved=validated,
        redacted=redacted,
        provenance=provenance,
        recipe_manifest=tuple(recipe_manifest),
        fingerprint=fingerprint,
    )


def _build_provenance(
    *,
    config_path: str,
    sources: tuple[ConfigSource, ...],
    overrides: tuple[ParsedOverride, ...],
    resolved_fingerprint: Fingerprint,
    recipe_manifest_count: int,
) -> ConfigProvenance:
    return ConfigProvenance(
        schema_version=SCHEMA_VERSION,
        config_path=config_path,
        sources=tuple(sources),
        overrides=overrides,
        resolved_fingerprint=resolved_fingerprint,
        recipe_manifest_count=recipe_manifest_count,
        metadata={},
    )


def build_resolved_fingerprint(validated: dict[str, PlainData]) -> str:
    from loom.fingerprints import hash_mapping

    return hash_mapping(validated)
