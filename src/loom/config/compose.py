"""Config composition orchestration."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import cast

from loom.fingerprints import Fingerprint
from loom.serialization import PlainData, to_plain_data

from .api import ComposedConfig, ConfigCompositionInspection, ConfigCompositionStageRecord
from .errors import ConfigErrorContext, ConfigIncludeExpansionError, ConfigLoadError, ConfigValidationError
from .includes import (
    IncludeRecompositionContext,
    IncludeSiteRecord,
    expand_config_includes,
    resolve_include_target,
)
from .interpolation import resolve_interpolation, scan_resolver_expressions
from .load import load_config
from .merge import merge_configs
from .artifacts import (
    SCHEMA_VERSION as ARTIFACT_SCHEMA_VERSION,
    CompositionManifest,
    ConfigFingerprintRecord,
    SourceArtifactRecord,
)
from .source_maps import ConfigPath, build_base_source_map, compose_config_with_sources, format_config_path
from .overrides import (
    ParsedOverride,
    apply_overrides,
    parse_overrides,
    split_include_and_ordinary_overrides,
)
from .provenance import (
    SCHEMA_VERSION as PROVENANCE_SCHEMA_VERSION,
    ConfigProvenance,
    ConfigSource,
    build_config_fingerprint,
)
from .redaction import redact_secrets
from .recipes import RecipeCatalog
from .recipes.expansion import expand_recipes, resolve_recipe_argument_interpolation
from .validation import validate_top_level_fields


_BARE_NAME_PATTERN: re.Pattern[str] = re.compile(r"^[A-Za-z0-9_-]+$")


def inspect_config_composition(
    config_path: str | Path,
    *,
    recipe_catalog: RecipeCatalog,
    overlays: Sequence[str | Path] = (),
    overrides: Sequence[str] = (),
) -> ConfigCompositionInspection:
    if not isinstance(recipe_catalog, RecipeCatalog):
        raise ConfigValidationError("recipe_catalog must be a RecipeCatalog")

    if overlays is None:
        raise ConfigValidationError("overlays may not be None")
    if overrides is None:
        raise ConfigValidationError("overrides may not be None")

    stages: list[ConfigCompositionStageRecord] = []

    base_config, base_source = load_config(config_path, kind="base", order=0)
    sources = [base_source]
    overlay_pairs: list[tuple[dict[str, PlainData], ConfigSource]] = []
    for order, overlay_path in enumerate(overlays, start=1):
        overlay_config, overlay_source = load_config(overlay_path, kind="overlay", order=order)
        sources.append(overlay_source)
        overlay_pairs.append((overlay_config, overlay_source))
    _append_stage(
        stages,
        "source_load",
        {
            "base_source": base_source.to_dict(),
            "overlay_sources": [overlay_source.to_dict() for _, overlay_source in overlay_pairs],
        },
    )

    merged_with_sources = compose_config_with_sources(
        base_config=base_config,
        base_source=base_source,
        overlays=overlay_pairs,
    )
    _append_stage(
        stages,
        "overlay_merge",
        {
            "source_count": len(sources),
            "overlay_count": len(overlay_pairs),
            "merged_keys": _config_key_count(merged_with_sources.config),
        },
    )

    expanded_with_includes = expand_config_includes(
        merged_with_sources.config,
        source_map=merged_with_sources.source_map,
        replacement_sites=merged_with_sources.replacement_sites,
        mapping_sites=merged_with_sources.mapping_sites,
    )
    _append_stage(
        stages,
        "file_include_expansion",
        {
            "include_site_count": len(expanded_with_includes.include_sites),
            "local_customization_count": len(expanded_with_includes.local_customizations),
            "recomposition_context_count": len(expanded_with_includes.recomposition_contexts),
        },
    )

    merged = expanded_with_includes.config

    parsed_overrides = parse_overrides(overrides)
    include_overrides, ordinary_overrides = split_include_and_ordinary_overrides(parsed_overrides)
    _append_stage(stages, "user_composition_overrides", {"requested_include_overrides": len(include_overrides)})

    if include_overrides:
        merged = _apply_user_composition_overrides(
            merged,
            include_overrides=include_overrides,
            include_records=expanded_with_includes.include_sites,
            recomposition_contexts=expanded_with_includes.recomposition_contexts,
            base_source=base_source,
        )

    _append_stage(
        stages,
        "recipe_argument_interpolation",
        {"status": "completed"},
    )
    resolved_recipe_args = resolve_recipe_argument_interpolation(merged, path="$")
    _append_stage(stages, "recipe_expansion", {"recipe_manifest_count": 0})
    expanded, recipe_manifest = expand_recipes(resolved_recipe_args, catalog=recipe_catalog, path="$")
    if stages[-1].name == "recipe_expansion":
        stages[-1] = ConfigCompositionStageRecord(
            name="recipe_expansion",
            status="completed",
            payload={
                "recipe_manifest_count": len(recipe_manifest),
            },
        )

    _append_stage(
        stages,
        "ordinary_overrides",
        {"ordinary_override_count": len(ordinary_overrides)},
    )
    merged = apply_overrides(expanded, ordinary_overrides)

    _append_stage(stages, "resolver_scan", {"resolver_expression_count": 0})
    expanded_artifact_safe, _resolver_records = scan_resolver_expressions(merged, path="$")
    if stages[-1].name == "resolver_scan":
        stages[-1] = ConfigCompositionStageRecord(
            name="resolver_scan",
            status="completed",
            payload={
                "resolver_expression_count": len(_resolver_records),
                "resolver_records": [
                    {
                        "config_path": record.config_path,
                        "token": record.token,
                        "resolver": record.resolver,
                        "expression": record.expression,
                    }
                    for record in _resolver_records
                ],
            },
        )

    _append_stage(
        stages,
        "runtime_interpolation",
        {
            "status": "completed",
            "input_key_count": _config_key_count(expanded_artifact_safe),
        },
    )
    unresolved = expanded_artifact_safe
    resolved = resolve_interpolation(
        expanded_artifact_safe,
        path="$",
        source_kind=base_source.kind,
        source_order=base_source.order,
        source_path=str(base_source.path),
    )
    validated = validate_top_level_fields(resolved)

    _append_stage(
        stages,
        "validation",
        {
            "status": "completed",
            "resolved_keys": _config_key_count(validated),
            "has_schema_version": "schema_version" in validated,
        },
    )
    redacted = redact_secrets(validated)
    _append_stage(stages, "redaction", {"redacted_keys": _config_key_count(redacted)})

    resolved_fingerprint = build_resolved_fingerprint(validated)
    provenance = _build_provenance(
        config_path=str(base_source.path),
        sources=tuple(sources),
        overrides=parsed_overrides,
        resolved_fingerprint=resolved_fingerprint,
        recipe_manifest_count=len(recipe_manifest),
    )
    _append_stage(stages, "provenance", {"source_count": len(sources), "override_count": len(parsed_overrides)})
    fingerprint = build_config_fingerprint(
        resolved=validated,
        sources=provenance.sources,
        overrides=provenance.overrides,
        recipe_manifest=recipe_manifest,
        schema_version=provenance.schema_version,
    )
    _append_stage(stages, "fingerprint", {"fingerprint": fingerprint})

    recipe_manifest_payload = tuple(
        cast(
            dict[str, PlainData],
            to_plain_data(_ensure_mappingproxy_plain(record), path=f"recipe_manifest[{index}]"),
        )
        for index, record in enumerate(recipe_manifest)
    )
    placeholder_manifest = CompositionManifest(
        schema_version=ARTIFACT_SCHEMA_VERSION,
        source_artifacts=(),
        fingerprint_records=(),
        recipe_manifest=recipe_manifest_payload,
        metadata={"phase": "12"},
    )
    source_artifacts: tuple[SourceArtifactRecord, ...] = ()
    fingerprint_records: tuple[ConfigFingerprintRecord, ...] = ()
    _append_stage(
        stages,
        "artifact_placeholders",
        {
            "manifest": {
                "schema_version": placeholder_manifest.schema_version,
                "source_artifacts": 0,
                "fingerprint_records": 0,
                "recipe_manifest_count": len(placeholder_manifest.recipe_manifest),
            },
            "source_artifact_count": len(source_artifacts),
            "fingerprint_record_count": len(fingerprint_records),
        },
    )

    _append_stage(
        stages,
        "composed_config",
        {
            "resolved_keys": _config_key_count(validated),
            "unresolved_keys": _config_key_count(unresolved),
        },
    )

    return ConfigCompositionInspection(
        stages=tuple(stages),
        unresolved=cast(dict[str, PlainData], to_plain_data(unresolved, path="unresolved")),
        resolved=validated,
        redacted=redacted,
        provenance=provenance,
        recipe_manifest=tuple(recipe_manifest),
        fingerprint=fingerprint,
        manifest=placeholder_manifest,
        source_artifacts=source_artifacts,
        fingerprint_records=fingerprint_records,
    )


def compose_config(
    config_path: str | Path,
    *,
    recipe_catalog: RecipeCatalog,
    overlays: Sequence[str | Path] = (),
    overrides: Sequence[str] = (),
) -> ComposedConfig:
    return inspect_config_composition(
        config_path=config_path,
        recipe_catalog=recipe_catalog,
        overlays=overlays,
        overrides=overrides,
    ).to_composed_config()


def _apply_user_composition_overrides(
    config: dict[str, PlainData],
    *,
    include_overrides: Sequence[ParsedOverride],
    include_records: Sequence[IncludeSiteRecord],
    recomposition_contexts: Sequence[IncludeRecompositionContext],
    base_source: ConfigSource,
) -> dict[str, PlainData]:
    include_record_by_path = {record.include_site_path: record for record in include_records}
    context_by_path = {context.include_site_path: context for context in recomposition_contexts}
    staged = cast(dict[str, PlainData], dict(config))

    for override in include_overrides:
        include_site_path = _include_site_path(override.path)
        context = context_by_path.get(include_site_path)
        include_record = include_record_by_path.get(include_site_path)

        if include_record is None:
            if override.operation != "add":
                raise _user_composition_error(
                    "Cannot update non-existent include site.",
                    code="missing_include_site",
                    source=base_source,
                    include_site_path=include_site_path,
                    override=override,
                    details={
                        "reason": "missing_existing_include_site",
                    },
                )

            staged = _add_brand_new_include_site(
                staged,
                include_override=override,
                include_site_path=include_site_path,
                base_source=base_source,
            )
            continue

        if override.operation == "add":
            raise _user_composition_error(
                "Cannot add an include at an existing recorded include site.",
                code="existing_include_site",
                source=_source_from_context(context) if context is not None else _source_from_record(include_record),
                include_site_path=include_site_path,
                override=override,
                details={
                    "reason": "add_existing_include_site",
                    "recorded_source_path": include_record.source_path,
                    "recorded_source_order": include_record.source_order,
                    "recorded_source_kind": include_record.source_kind,
                },
            )

        if context is not None:
            staged = _replace_existing_include_site(
                staged,
                include_override=override,
                context=context,
            )
            continue

        raise _user_composition_error(
            "Existing include site lacks recomposition context needed for user override replay.",
            code="missing_recomposition_context",
            source=_source_from_record(include_record),
            include_site_path=include_site_path,
            override=override,
            details={
                "reason": "missing_recomposition_context",
                "recorded_source_path": include_record.source_path,
                "recorded_source_order": include_record.source_order,
                "recorded_source_kind": include_record.source_kind,
            },
        )

    return staged


def _replace_existing_include_site(
    config: dict[str, PlainData],
    *,
    include_override: ParsedOverride,
    context: IncludeRecompositionContext,
) -> dict[str, PlainData]:
    authored_target = _as_include_target(
        include_override,
        source=_source_from_context(context),
        include_site_path=context.include_site_path,
    )
    replacement_source = _source_from_context(context)
    resolved = resolve_include_target(
        authored_target,
        source=replacement_source,
        include_site_path=context.source_include_site_path,
    )

    replacement = _load_include_target(
        path=resolved.resolved_path,
        source=replacement_source,
        include_site_path=context.include_site_path,
        override=include_override,
    )
    replacement = _replay_local_customizations(replacement, context=context)
    return _set_value(
        config,
        path=context.include_site_path[:-1],
        value=replacement,
        source=replacement_source,
        override=include_override,
    )


def _add_brand_new_include_site(
    config: dict[str, PlainData],
    *,
    include_override: ParsedOverride,
    include_site_path: ConfigPath,
    base_source: ConfigSource,
) -> dict[str, PlainData]:
    authored_target = _as_include_target(
        include_override,
        source=base_source,
        include_site_path=include_site_path,
    )
    if _is_bare_name_target(authored_target):
        raise _user_composition_error(
            "New include sites require explicit include targets.",
            code="new_include_requires_explicit_target",
            source=base_source,
            include_site_path=include_site_path,
            override=include_override,
            details={
                "reason": "explicit_target_required",
                "authored_target": authored_target,
            },
        )

    resolved = resolve_include_target(
        authored_target,
        source=base_source,
        include_site_path=include_site_path,
    )

    parent, key = _ensure_include_parent_path(
        config=config,
        path=include_site_path[:-1],
        source=base_source,
        override=include_override,
        allow_create=True,
    )
    if key in parent:
        raise _user_composition_error(
            "Cannot add a new include at an existing concrete include site parent.",
            code="existing_include_container",
            source=base_source,
            include_site_path=include_site_path,
            override=include_override,
            details={
                "reason": "container_exists",
                "container_path": _format_path(include_site_path[:-1]),
            },
        )

    replacement = _load_include_target(
        path=resolved.resolved_path,
        source=base_source,
        include_site_path=include_site_path,
        override=include_override,
    )
    parent[key] = replacement
    return config


def _replay_local_customizations(
    replacement: dict[str, PlainData],
    *,
    context: IncludeRecompositionContext,
) -> dict[str, PlainData]:
    if not context.local_customizations:
        return replacement

    overlay: dict[str, PlainData] = {}
    for record in context.local_customizations:
        sibling_key = record.sibling_path[-1]
        if not isinstance(sibling_key, str):
            continue
        overlay[sibling_key] = record.value

    return merge_configs(
        replacement,
        overlay,
        path=format_config_path(context.include_site_path[:-1]),
    )


def _load_include_target(
    *,
    path: str | Path,
    source: ConfigSource,
    include_site_path: ConfigPath,
    override: ParsedOverride,
) -> dict[str, PlainData]:
    try:
        included_config, included_source = load_config(path, kind="overlay", order=0)
    except ConfigLoadError as exc:
        if exc.context is None or exc.context.code != "non_mapping_root":
            raise
        raise _user_composition_error(
            "Included include replacement target did not resolve to a mapping.",
            code="included_root_not_mapping",
            source=source,
            include_site_path=include_site_path,
            override=override,
            details={
                "reason": "replacement_root_not_mapping",
                "resolved_path": str(path),
                "included_source_path": exc.context.source_path,
                "included_config_path": exc.context.config_path,
                "expected": exc.context.expected,
                "actual": exc.context.actual,
            },
        ) from exc
    expanded = expand_config_includes(
        included_config,
        source_map=build_base_source_map(included_config, included_source),
        replacement_sites=(),
        mapping_sites=(),
        reject_unconsumed_replace_markers=True,
    )

    if not isinstance(expanded.config, Mapping):
        raise _user_composition_error(
            "Included include replacement target did not resolve to a mapping.",
            code="included_root_not_mapping",
            source=source,
            include_site_path=include_site_path,
            override=override,
            details={
                "reason": "replacement_root_not_mapping",
                "resolved_path": str(path),
                "target_type": str(type(expanded.config).__name__),
            },
        )

    return cast(dict[str, PlainData], expanded.config)


def _set_value(
    config: dict[str, PlainData],
    *,
    path: ConfigPath,
    value: PlainData,
    source: ConfigSource,
    override: ParsedOverride,
) -> dict[str, PlainData]:
    if not isinstance(value, Mapping):
        raise _user_composition_error(
            "Composition replacement value must be a mapping.",
            code="invalid_include_container",
            source=source,
            include_site_path=path,
            override=override,
            details={"reason": "replacement_not_mapping"},
        )

    if not path:
        config.clear()
        config.update(cast(dict[str, PlainData], value))
        return config

    parent, key = _ensure_include_parent_path(
        config=config,
        path=path,
        source=source,
        override=override,
        allow_create=False,
    )
    parent[key] = value
    return config


def _ensure_include_parent_path(
    *,
    config: dict[str, PlainData],
    path: ConfigPath,
    source: ConfigSource,
    override: ParsedOverride,
    allow_create: bool,
) -> tuple[dict[str, PlainData], str]:
    if not path:
        raise _user_composition_error(
            "Cannot address the configuration root for include stage updates.",
            code="invalid_include_parent",
            source=source,
            include_site_path=path,
            override=override,
            details={"reason": "missing_target_parent"},
        )

    parent: dict[str, PlainData] = config
    for index, segment in enumerate(path[:-1]):
        if not isinstance(segment, str):
            raise _user_composition_error(
                "Cannot target non-string include override path segments.",
                code="invalid_include_parent_segment",
                source=source,
                include_site_path=path,
                override=override,
                details={
                    "reason": "non_string_segment",
                    "parent_path": _format_path(path[: index + 1]),
                    "segment": segment,
                },
            )
        child = parent.get(segment)
        if child is None:
            if not allow_create:
                raise _user_composition_error(
                    "Cannot write include composition override into a missing parent path.",
                    code="missing_include_parent",
                    source=source,
                    include_site_path=path,
                    override=override,
                    details={
                        "reason": "missing_parent",
                        "parent_path": _format_path(path[:-1]),
                        "segment": segment,
                    },
                )
            new_value: dict[str, PlainData] = {}
            parent[segment] = new_value
            parent = new_value
            continue

        if not isinstance(child, dict):
            raise _user_composition_error(
                "Cannot set include override under a non-mapping parent.",
                code="invalid_include_parent_type",
                source=source,
                include_site_path=path,
                override=override,
                details={
                    "reason": "parent_not_mapping",
                    "parent_path": _format_path(path[: index + 1]),
                    "value_type": type(child).__name__,
                },
            )

        parent = child

    final_segment = path[-1]
    if not isinstance(final_segment, str):
        raise _user_composition_error(
            "Cannot target include parent with non-string final path segment.",
            code="invalid_include_parent_segment",
            source=source,
            include_site_path=path,
            override=override,
            details={
                "reason": "non_string_segment",
                "parent_path": _format_path(path),
                "segment": final_segment,
            },
        )

    return parent, final_segment


def _include_site_path(path: str) -> ConfigPath:
    return tuple(path.split(".")[:-1]) + ("_include_",)


def _as_include_target(
    override: ParsedOverride,
    *,
    source: ConfigSource,
    include_site_path: ConfigPath,
) -> str:
    value = override.value
    if not isinstance(value, str):
        raise _user_composition_error(
            "Include override target must be a string.",
            code="invalid_include_value",
            source=source,
            include_site_path=include_site_path,
            override=override,
            details={
                "reason": "non_string_include_target",
                "value": str(value),
            },
        )
    return value


def _is_bare_name_target(value: str) -> bool:
    return _BARE_NAME_PATTERN.fullmatch(value) is not None


def _format_path(path: ConfigPath) -> list[str | int]:
    return [segment for segment in path]


def _source_from_context(context: IncludeRecompositionContext) -> ConfigSource:
    return ConfigSource(
        kind=context.source_kind,
        path=context.source_path,
        order=context.source_order,
        content_digest=context.source_content_digest,
        size_bytes=context.source_size_bytes,
    )


def _source_from_record(record: IncludeSiteRecord) -> ConfigSource:
    return ConfigSource(
        kind=record.source_kind,
        path=record.source_path,
        order=record.source_order,
        content_digest=record.source_content_digest,
        size_bytes=record.source_size_bytes,
    )


def _user_composition_error(
    message: str,
    *,
    code: str,
    source: ConfigSource,
    include_site_path: ConfigPath,
    override: ParsedOverride | None = None,
    details: dict[str, object] | None = None,
) -> Exception:
    payload: dict[str, object] = dict(details or {})
    payload["include_site_path"] = _format_path(include_site_path)

    if override is not None:
        payload["override_order"] = override.order
        payload["override_raw"] = override.raw
        payload["override_path"] = override.path
        payload["override_operation"] = override.operation

    return ConfigIncludeExpansionError(
        message,
        context=ConfigErrorContext(
            code=code,
            source_kind=source.kind,
            source_order=source.order,
            source_path=source.path,
            config_path=format_config_path(include_site_path),
            directive="_include_",
            details=cast(dict[str, PlainData], to_plain_data(payload)),
        ),
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
        schema_version=PROVENANCE_SCHEMA_VERSION,
        config_path=config_path,
        sources=tuple(sources),
        overrides=overrides,
        resolved_fingerprint=resolved_fingerprint,
        recipe_manifest_count=recipe_manifest_count,
        metadata={},
    )


def _append_stage(stages: list[ConfigCompositionStageRecord], name: str, payload: Mapping[str, object]) -> None:
    payload_data = cast(dict[str, PlainData], to_plain_data(dict(payload), path=f"stage[{name}]"))
    stages.append(
        ConfigCompositionStageRecord(
            name=name,
            status="completed",
            payload=payload_data,
        )
    )


def _ensure_mappingproxy_plain(value: object) -> object:
    if isinstance(value, MappingProxyType):
        value = dict(value)
    if isinstance(value, Mapping):
        return {str(key): _ensure_mappingproxy_plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_ensure_mappingproxy_plain(item) for item in value]
    if isinstance(value, tuple):
        return [_ensure_mappingproxy_plain(item) for item in value]
    return value


def _config_key_count(config: Mapping[str, PlainData]) -> int:
    return len(config)


def build_resolved_fingerprint(validated: dict[str, PlainData]) -> str:
    from loom.fingerprints import hash_mapping

    return hash_mapping(validated)
