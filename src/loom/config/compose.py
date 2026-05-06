"""Config composition orchestration."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import cast

from loom.fingerprints import Fingerprint
from loom.serialization import PlainData, to_plain_data

from .api import ComposedConfig, ConfigCompositionInspection, ConfigCompositionStageRecord
from .errors import ConfigErrorContext, ConfigIncludeExpansionError, ConfigLoadError, ConfigValidationError
from .includes import (
    IncludeRecompositionContext,
    IncludeLocalCustomization,
    IncludeResolutionResult,
    IncludeSiteRecord,
    expand_config_includes,
    resolve_include_target,
)
from .interpolation import resolve_interpolation, scan_resolver_expressions
from .load import load_config
from .load import load_config_with_source_text
from .merge import merge_configs
from .artifacts import (
    SCHEMA_VERSION as ARTIFACT_SCHEMA_VERSION,
    CompositionManifest,
    RawSourceSnapshotBundle,
    RawSourceSnapshotPayload,
    RawSourceSnapshotReference,
    SourceArtifactRecord,
)
from .fingerprints import (
    build_artifact_safe_config_fingerprint_record,
)
from .source_maps import (
    ConfigPath,
    ValueAuthorship,
    build_base_source_map,
    compose_config_with_sources,
    format_config_path,
)
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
)
from .redaction import (
    REDACTION_MARKER,
    contains_secret_like_value,
    is_secret_path,
    redaction_policy,
    redact_secret_like_value,
    redact_secrets,
)
from .recipes import RecipeCatalog
from .recipes.expansion import expand_recipes, resolve_recipe_argument_interpolation
from .interpolation import ResolverExpressionRecord
from .validation import validate_top_level_fields


_BARE_NAME_PATTERN: re.Pattern[str] = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True, slots=True)
class _UserCompositionResult:
    config: dict[str, PlainData]
    include_records: tuple[IncludeSiteRecord, ...]


def inspect_config_composition(
    config_path: str | Path,
    *,
    recipe_catalog: RecipeCatalog,
    overlays: Sequence[str | Path] = (),
    overrides: Sequence[str] = (),
    include_raw_source_snapshots: bool = False,
) -> ConfigCompositionInspection:
    if not isinstance(recipe_catalog, RecipeCatalog):
        raise ConfigValidationError("recipe_catalog must be a RecipeCatalog")

    if overlays is None:
        raise ConfigValidationError("overlays may not be None")
    if overrides is None:
        raise ConfigValidationError("overrides may not be None")
    if not isinstance(include_raw_source_snapshots, bool):
        raise ConfigValidationError("include_raw_source_snapshots must be a bool")

    stages: list[ConfigCompositionStageRecord] = []
    raw_source_texts: dict[str, str] | None = {} if include_raw_source_snapshots else None

    if include_raw_source_snapshots:
        base_config, base_source, base_text = load_config_with_source_text(
            config_path,
            kind="base",
            order=0,
        )
        if raw_source_texts is not None:
            raw_source_texts[base_source.path] = base_text
    else:
        base_config, base_source = load_config(config_path, kind="base", order=0)
    sources = [base_source]
    overlay_pairs: list[tuple[dict[str, PlainData], ConfigSource]] = []
    for order, overlay_path in enumerate(overlays, start=1):
        if include_raw_source_snapshots:
            overlay_config, overlay_source, overlay_text = load_config_with_source_text(
                overlay_path,
                kind="overlay",
                order=order,
            )
            if raw_source_texts is not None:
                raw_source_texts[overlay_source.path] = overlay_text
        else:
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
        raw_source_texts=raw_source_texts,
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

    effective_include_sites = expanded_with_includes.include_sites
    if include_overrides:
        user_composition = _apply_user_composition_overrides(
            merged,
            include_overrides=include_overrides,
            include_records=expanded_with_includes.include_sites,
            recomposition_contexts=expanded_with_includes.recomposition_contexts,
            base_source=base_source,
            raw_source_texts=raw_source_texts,
        )
        merged = user_composition.config
        replaced_include_containers = {
            _include_site_path(override.path)[:-1]
            for override in include_overrides
            if override.operation == "update"
        }
        replaced_include_paths = {
            _include_site_path(override.path)
            for override in include_overrides
            if override.operation == "update"
        }
        effective_include_sites = (
            *(
                record
                for record in expanded_with_includes.include_sites
                if record.include_site_path not in replaced_include_paths
                and not _is_descendant_include_record(record, replaced_include_containers)
            ),
            *user_composition.include_records,
        )

    _append_stage(
        stages,
        "recipe_argument_interpolation",
        {"status": "completed"},
    )
    resolved_recipe_args = resolve_recipe_argument_interpolation(merged, path="$")
    _append_stage(stages, "recipe_expansion", {"recipe_manifest_count": 0})
    expanded, recipe_manifest = expand_recipes(resolved_recipe_args, catalog=recipe_catalog, path="$")
    recipe_manifest_payload = tuple(
        cast(
            dict[str, PlainData],
            to_plain_data(_ensure_mappingproxy_plain(record), path=f"recipe_manifest[{index}]"),
        )
        for index, record in enumerate(recipe_manifest)
    )
    if stages[-1].name == "recipe_expansion":
        stages[-1] = ConfigCompositionStageRecord(
            name="recipe_expansion",
            status="completed",
            payload={
                "recipe_manifest_count": len(recipe_manifest_payload),
            },
        )

    _append_stage(
        stages,
        "ordinary_overrides",
        {"ordinary_override_count": len(ordinary_overrides)},
    )
    merged = apply_overrides(expanded, ordinary_overrides)
    value_authorship = _build_final_value_authorship(
        config=merged,
        merged_source_map=merged_with_sources.source_map,
        include_records=effective_include_sites,
        local_customizations=expanded_with_includes.local_customizations,
        ordinary_overrides=ordinary_overrides,
        recipe_manifest=recipe_manifest_payload,
    )

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
    redacted = redact_secrets(unresolved)
    resolved = resolve_interpolation(
        expanded_artifact_safe,
        path="$",
        source_kind=base_source.kind,
        source_order=base_source.order,
        source_path=str(base_source.path),
        value_authorship={
            format_config_path(path): authorship for path, authorship in value_authorship.items()
        },
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
    _append_stage(stages, "redaction", {"redacted_keys": _config_key_count(redacted), "marker": REDACTION_MARKER})

    source_artifacts = _build_source_artifacts(
        sources=sources,
        include_sites=effective_include_sites,
        recipe_manifest=recipe_manifest_payload,
    )
    raw_source_snapshot_bundle = _build_raw_source_snapshot_bundle(
        sources=source_artifacts,
        include_raw_source_snapshots=include_raw_source_snapshots,
        raw_source_texts=raw_source_texts,
    )
    artifact_safe_config_fingerprint_record = build_artifact_safe_config_fingerprint_record(
        unresolved=unresolved,
        redacted=redacted,
        source_artifacts=source_artifacts,
        include_sites=effective_include_sites,
        include_overrides=include_overrides,
        ordinary_overrides=ordinary_overrides,
        recipe_manifest=recipe_manifest_payload,
        resolver_records=_resolver_records,
        redaction_policy=redaction_policy(),
    )
    fingerprint_records = (artifact_safe_config_fingerprint_record,)
    resolved_fingerprint = build_resolved_fingerprint(validated)
    provenance_metadata = _build_provenance_metadata(
        include_records=effective_include_sites,
        recomposition_contexts=expanded_with_includes.recomposition_contexts,
        local_customizations=expanded_with_includes.local_customizations,
        include_overrides=include_overrides,
        ordinary_overrides=ordinary_overrides,
        recipe_manifest=recipe_manifest_payload,
        resolver_records=_resolver_records,
        source_artifacts=source_artifacts,
        value_authorship=value_authorship,
        redaction_policy=redaction_policy(),
        warnings=_plaintext_secret_warnings(tuple(include_overrides) + tuple(ordinary_overrides)),
        raw_source_snapshot_references=[
            reference.to_dict() for reference in raw_source_snapshot_bundle.references
        ],
    )
    manifest_metadata = dict(provenance_metadata)
    manifest_metadata["artifact_schema_version"] = ARTIFACT_SCHEMA_VERSION
    manifest_metadata["source_reference_count"] = len(source_artifacts)
    manifest_metadata["fingerprint_record_count"] = len(fingerprint_records)
    manifest_metadata["source_artifact_references"] = [
        _to_source_artifact_reference(record) for record in source_artifacts
    ]
    manifest_metadata["raw_source_snapshot_references"] = [
        reference.to_dict() for reference in raw_source_snapshot_bundle.references
    ]
    manifest_metadata["raw_source_snapshot_enabled"] = raw_source_snapshot_bundle.enabled

    provenance = _build_provenance(
        config_path=str(base_source.path),
        sources=tuple(sources),
        overrides=parsed_overrides,
        resolved_fingerprint=resolved_fingerprint,
        recipe_manifest_count=len(recipe_manifest_payload),
        metadata=provenance_metadata,
    )
    _append_stage(
        stages,
        "provenance",
        {
            "source_count": len(sources),
            "override_count": len(parsed_overrides),
            "source_artifact_count": len(source_artifacts),
            "resolver_record_count": len(_resolver_records),
            "recipe_manifest_count": len(recipe_manifest_payload),
            "fingerprint_record_count": len(fingerprint_records),
            "raw_source_snapshot_reference_count": len(raw_source_snapshot_bundle.references),
            "raw_source_snapshot_enabled": raw_source_snapshot_bundle.enabled,
        },
    )
    fingerprint = artifact_safe_config_fingerprint_record.digest
    _append_stage(
        stages,
        "fingerprint",
        {
            "fingerprint": fingerprint,
            "fingerprint_record_count": len(fingerprint_records),
        },
    )

    placeholder_manifest = CompositionManifest(
        schema_version=ARTIFACT_SCHEMA_VERSION,
        source_artifacts=source_artifacts,
        fingerprint_records=fingerprint_records,
        recipe_manifest=recipe_manifest_payload,
        metadata=manifest_metadata,
    )
    _append_stage(
        stages,
        "artifact_placeholders",
        {
            "manifest": {
                "schema_version": placeholder_manifest.schema_version,
                "source_artifacts": len(placeholder_manifest.source_artifacts),
                "fingerprint_records": len(placeholder_manifest.fingerprint_records),
                "recipe_manifest_count": len(placeholder_manifest.recipe_manifest),
            },
            "source_artifact_count": len(placeholder_manifest.source_artifacts),
            "fingerprint_record_count": len(placeholder_manifest.fingerprint_records),
            "source_reference_count": len(manifest_metadata["source_artifact_references"]),
            "raw_source_snapshot_reference_count": len(
                manifest_metadata["raw_source_snapshot_references"]
            ),
            "raw_source_snapshot_payload_count": len(raw_source_snapshot_bundle.payloads),
            "raw_source_snapshot_enabled": raw_source_snapshot_bundle.enabled,
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
        recipe_manifest=tuple(recipe_manifest_payload),
        fingerprint=fingerprint,
        manifest=placeholder_manifest,
        source_artifacts=source_artifacts,
        fingerprint_records=fingerprint_records,
        raw_source_snapshots=raw_source_snapshot_bundle,
    )


def compose_config(
    config_path: str | Path,
    *,
    recipe_catalog: RecipeCatalog,
    overlays: Sequence[str | Path] = (),
    overrides: Sequence[str] = (),
    include_raw_source_snapshots: bool = False,
) -> ComposedConfig:
    return inspect_config_composition(
        config_path=config_path,
        recipe_catalog=recipe_catalog,
        overlays=overlays,
        overrides=overrides,
        include_raw_source_snapshots=include_raw_source_snapshots,
    ).to_composed_config()


def _apply_user_composition_overrides(
    config: dict[str, PlainData],
    *,
    include_overrides: Sequence[ParsedOverride],
    include_records: Sequence[IncludeSiteRecord],
    recomposition_contexts: Sequence[IncludeRecompositionContext],
    base_source: ConfigSource,
    raw_source_texts: dict[str, str] | None,
) -> _UserCompositionResult:
    include_record_by_path = {record.include_site_path: record for record in include_records}
    context_by_path = {context.include_site_path: context for context in recomposition_contexts}
    staged = cast(dict[str, PlainData], dict(config))
    user_include_records: list[IncludeSiteRecord] = []

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

            staged, include_records = _add_brand_new_include_site(
                staged,
                include_override=override,
                include_site_path=include_site_path,
                base_source=base_source,
                raw_source_texts=raw_source_texts,
            )
            user_include_records.extend(include_records)
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
            staged, include_records = _replace_existing_include_site(
                staged,
                include_override=override,
                context=context,
                raw_source_texts=raw_source_texts,
            )
            user_include_records.extend(include_records)
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

    return _UserCompositionResult(config=staged, include_records=tuple(user_include_records))


def _replace_existing_include_site(
    config: dict[str, PlainData],
    *,
    include_override: ParsedOverride,
    context: IncludeRecompositionContext,
    raw_source_texts: dict[str, str] | None,
) -> tuple[dict[str, PlainData], tuple[IncludeSiteRecord, ...]]:
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

    replacement, include_records = _load_include_target(
        path=resolved.resolved_path,
        source=replacement_source,
        include_site_path=context.include_site_path,
        source_include_site_path=context.source_include_site_path,
        resolved=resolved,
        override=include_override,
        raw_source_texts=raw_source_texts,
    )
    replacement = _replay_local_customizations(replacement, context=context)
    staged = _set_value(
        config,
        path=context.include_site_path[:-1],
        value=replacement,
        source=replacement_source,
        override=include_override,
    )
    return staged, include_records


def _add_brand_new_include_site(
    config: dict[str, PlainData],
    *,
    include_override: ParsedOverride,
    include_site_path: ConfigPath,
    base_source: ConfigSource,
    raw_source_texts: dict[str, str] | None,
) -> tuple[dict[str, PlainData], tuple[IncludeSiteRecord, ...]]:
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

    replacement, include_records = _load_include_target(
        path=resolved.resolved_path,
        source=base_source,
        include_site_path=include_site_path,
        source_include_site_path=include_site_path,
        resolved=resolved,
        override=include_override,
        raw_source_texts=raw_source_texts,
    )
    parent[key] = replacement
    return config, include_records


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
    source_include_site_path: ConfigPath,
    resolved: IncludeResolutionResult,
    override: ParsedOverride,
    raw_source_texts: dict[str, str] | None,
) -> tuple[dict[str, PlainData], tuple[IncludeSiteRecord, ...]]:
    try:
        if raw_source_texts is None:
            included_config, included_source = load_config(path, kind="overlay", order=0)
        else:
            included_config, included_source, source_text = load_config_with_source_text(
                path,
                kind="overlay",
                order=0,
            )
            raw_source_texts[included_source.path] = source_text
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
        path_prefix=include_site_path[:-1],
        replacement_sites=(),
        mapping_sites=(),
        reject_unconsumed_replace_markers=True,
        raw_source_texts=raw_source_texts,
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

    include_record = IncludeSiteRecord(
        include_site_path=include_site_path,
        authored_target=resolved.authored_target,
        source_path=resolved.source_path,
        source_kind=source.kind,
        source_order=source.order,
        source_include_site_path=source_include_site_path,
        source_content_digest=source.content_digest,
        source_size_bytes=source.size_bytes,
        resolved_path=str(resolved.resolved_path),
        included_content_digest=included_source.content_digest,
        included_size_bytes=included_source.size_bytes,
        target_kind=resolved.target_kind,
        explicit_escape=resolved.explicit_escape,
        has_replace_marker=False,
    )

    return cast(dict[str, PlainData], expanded.config), (
        include_record,
        *expanded.include_sites,
    )


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


def _is_descendant_include_record(
    record: IncludeSiteRecord,
    replaced_include_containers: set[ConfigPath],
) -> bool:
    return any(
        record.include_site_path[: len(container_path)] == container_path
        for container_path in replaced_include_containers
    )


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
                "value_type": type(value).__name__,
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
        payload["override_raw"] = _safe_override_raw(override)
        payload["override_path"] = override.path
        payload["override_operation"] = override.operation
        payload["override_redacted"] = _override_is_redacted(override)

    return ConfigIncludeExpansionError(
        message,
        context=ConfigErrorContext(
            code=code,
            source_kind=source.kind,
            source_order=source.order,
            source_path=source.path,
            config_path=format_config_path(include_site_path),
            directive="_include_",
            remediation=_remediation_for_user_composition(code),
            details=cast(dict[str, PlainData], to_plain_data(payload)),
        ),
    )


def _remediation_for_user_composition(code: str) -> str | None:
    return {
        "missing_include_site": "Use an add override with a new explicit include target, or update an existing _include_ site.",
        "existing_include_site": "Use update syntax for an existing _include_ site replacement.",
        "new_include_requires_explicit_target": "Use an explicit relative, absolute, or file:// include target for new include sites.",
        "invalid_include_value": "Set _include_ override values to a string target.",
        "missing_include_parent": "Add the parent mapping first or target an existing include site.",
        "invalid_include_parent_type": "Choose a mapping parent path for include composition overrides.",
    }.get(code)


def _safe_override_raw(override: ParsedOverride) -> str:
    return REDACTION_MARKER if _override_is_redacted(override) else override.raw


def _override_is_redacted(override: ParsedOverride) -> bool:
    final_key = override.path.rsplit(".", 1)[-1]
    return contains_secret_like_value(final_key, override.value) or is_secret_path(override.path)


def _build_raw_source_snapshot_bundle(
    *,
    sources: Sequence[SourceArtifactRecord],
    include_raw_source_snapshots: bool,
    raw_source_texts: dict[str, str] | None,
) -> RawSourceSnapshotBundle:
    payloads: list[RawSourceSnapshotPayload] = []
    references: list[RawSourceSnapshotReference] = []
    payload_by_digest_and_size: dict[tuple[str, int], str] = {}

    for source in sources:
        if source.kind == "recipe":
            references.append(
                RawSourceSnapshotReference(
                    kind="recipe",
                    order=source.order,
                    path=source.path,
                    content_digest=source.content_digest,
                    size_bytes=source.size_bytes,
                    availability="unavailable",
                    payload_id=None,
                    reason="unsupported_source_kind",
                )
            )
            continue

        if not include_raw_source_snapshots:
            references.append(
                RawSourceSnapshotReference(
                    kind=source.kind,
                    order=source.order,
                    path=source.path,
                    content_digest=source.content_digest,
                    size_bytes=source.size_bytes,
                    availability="disabled",
                    payload_id=None,
                    reason="not_requested",
                )
            )
            continue

        if raw_source_texts is None:
            references.append(
                RawSourceSnapshotReference(
                    kind=source.kind,
                    order=source.order,
                    path=source.path,
                    content_digest=source.content_digest,
                    size_bytes=source.size_bytes,
                    availability="disabled",
                    payload_id=None,
                    reason="not_requested",
                )
            )
            continue

        content = raw_source_texts.get(source.path)
        if content is None:
            references.append(
                RawSourceSnapshotReference(
                    kind=source.kind,
                    order=source.order,
                    path=source.path,
                    content_digest=source.content_digest,
                    size_bytes=source.size_bytes,
                    availability="unavailable",
                    payload_id=None,
                    reason="raw_capture_unavailable",
                )
            )
            continue

        key = (source.content_digest, source.size_bytes)
        payload_id = payload_by_digest_and_size.get(key)
        if payload_id is None:
            payload_id = f"{source.content_digest}:{source.size_bytes}"
            payload_by_digest_and_size[key] = payload_id
            payloads.append(
                RawSourceSnapshotPayload(
                    payload_id=payload_id,
                    content=content,
                    content_digest=source.content_digest,
                    size_bytes=source.size_bytes,
                )
            )

        references.append(
            RawSourceSnapshotReference(
                kind=source.kind,
                order=source.order,
                path=source.path,
                content_digest=source.content_digest,
                size_bytes=source.size_bytes,
                availability="available",
                payload_id=payload_id,
                reason="requested",
            )
        )

    return RawSourceSnapshotBundle(
        schema_version=ARTIFACT_SCHEMA_VERSION,
        enabled=include_raw_source_snapshots and raw_source_texts is not None,
        payloads=tuple(payloads),
        references=tuple(references),
        metadata={
            "request": include_raw_source_snapshots,
            "enabled": include_raw_source_snapshots and raw_source_texts is not None,
            "source_count": len(sources),
            "payload_count": len(payloads),
            "reference_count": len(references),
        },
    )


def _build_provenance(
    *,
    config_path: str,
    sources: tuple[ConfigSource, ...],
    overrides: tuple[ParsedOverride, ...],
    resolved_fingerprint: Fingerprint,
    recipe_manifest_count: int,
    metadata: dict[str, PlainData],
) -> ConfigProvenance:
    return ConfigProvenance(
        schema_version=PROVENANCE_SCHEMA_VERSION,
        config_path=config_path,
        sources=tuple(sources),
        overrides=overrides,
        resolved_fingerprint=resolved_fingerprint,
        recipe_manifest_count=recipe_manifest_count,
        metadata=metadata,
    )


def _build_source_artifacts(
    *,
    sources: Sequence[ConfigSource],
    include_sites: Sequence[IncludeSiteRecord],
    recipe_manifest: Sequence[Mapping[str, PlainData]],
) -> tuple[SourceArtifactRecord, ...]:
    artifacts: list[SourceArtifactRecord] = []
    for source in sources:
        artifacts.append(
            SourceArtifactRecord(
                schema_version=ARTIFACT_SCHEMA_VERSION,
                kind=source.kind,
                path=source.path,
                order=source.order,
                content_digest=source.content_digest,
                size_bytes=source.size_bytes,
                metadata={
                    "role": "base_or_overlay",
                    "raw_snapshot": _metadata_only_raw_snapshot_limits(source_kind=source.kind),
                },
            )
        )
    start_order = len(sources)
    artifacts.extend(_build_include_source_artifacts(include_sites=include_sites, start_order=start_order))
    recipe_start = start_order + len(include_sites)
    artifacts.extend(_build_recipe_source_artifacts(recipe_manifest=recipe_manifest, start_order=recipe_start))
    return tuple(artifacts)


def _build_final_value_authorship(
    *,
    config: Mapping[str, PlainData],
    merged_source_map: Mapping[ConfigPath, ConfigSource],
    include_records: Sequence[IncludeSiteRecord],
    local_customizations: Sequence[IncludeLocalCustomization],
    ordinary_overrides: Sequence[ParsedOverride],
    recipe_manifest: Sequence[Mapping[str, PlainData]],
) -> dict[ConfigPath, ValueAuthorship]:
    records: dict[ConfigPath, ValueAuthorship] = {}
    for path in _iter_value_paths(config):
        authorship = _authorship_from_source_map(path=path, source_map=merged_source_map)
        include_authorship = _authorship_from_include_records(path=path, include_records=include_records)
        if include_authorship is not None:
            authorship = include_authorship
        customization_authorship = _authorship_from_local_customizations(
            path=path,
            local_customizations=local_customizations,
        )
        if customization_authorship is not None:
            authorship = customization_authorship
        recipe_authorship = _authorship_from_recipe_manifest(path=path, recipe_manifest=recipe_manifest)
        if recipe_authorship is not None:
            authorship = recipe_authorship
        override_authorship = _authorship_from_ordinary_overrides(path=path, ordinary_overrides=ordinary_overrides)
        if override_authorship is not None:
            authorship = override_authorship
        if authorship is not None:
            records[path] = authorship
    return records


def _iter_value_paths(value: object, path: ConfigPath = ()) -> tuple[ConfigPath, ...]:
    paths = [path]
    if isinstance(value, Mapping):
        for key, child in value.items():
            paths.extend(_iter_value_paths(child, path + (str(key),)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_iter_value_paths(child, path + (index,)))
    return tuple(paths)


def _authorship_from_source_map(
    *,
    path: ConfigPath,
    source_map: Mapping[ConfigPath, ConfigSource],
) -> ValueAuthorship | None:
    source = source_map.get(path)
    if source is None:
        source = _nearest_source(path=path, source_map=source_map)
    if source is None:
        return None
    return ValueAuthorship(
        path=path,
        source_kind=source.kind,
        source_path=source.path,
        source_order=source.order,
        source_content_digest=source.content_digest,
        source_size_bytes=source.size_bytes,
        composition_stage="source_load",
    )


def _nearest_source(
    *,
    path: ConfigPath,
    source_map: Mapping[ConfigPath, ConfigSource],
) -> ConfigSource | None:
    for length in range(len(path), -1, -1):
        source = source_map.get(path[:length])
        if source is not None:
            return source
    return None


def _authorship_from_include_records(
    *,
    path: ConfigPath,
    include_records: Sequence[IncludeSiteRecord],
) -> ValueAuthorship | None:
    best: IncludeSiteRecord | None = None
    best_container: ConfigPath = ()
    for record in include_records:
        container = record.include_site_path[:-1]
        if path[: len(container)] != container:
            continue
        if best is None or len(container) > len(best_container):
            best = record
            best_container = container
    if best is None:
        return None
    return ValueAuthorship(
        path=path,
        source_kind="include",
        source_path=best.resolved_path,
        source_order=best.source_order,
        source_content_digest=best.included_content_digest,
        source_size_bytes=best.included_size_bytes,
        composition_stage="file_include_expansion",
        details={
            "include_site_path": list(best.include_site_path),
            "source_path": best.source_path,
            "source_kind": best.source_kind,
            "source_order": best.source_order,
            "source_include_site_path": list(best.source_include_site_path),
            "target_kind": best.target_kind,
            "explicit_escape": best.explicit_escape,
            "has_replace_marker": best.has_replace_marker,
        },
    )


def _authorship_from_local_customizations(
    *,
    path: ConfigPath,
    local_customizations: Sequence[IncludeLocalCustomization],
) -> ValueAuthorship | None:
    best: IncludeLocalCustomization | None = None
    for record in local_customizations:
        if path[: len(record.sibling_path)] != record.sibling_path:
            continue
        if best is None or len(record.sibling_path) > len(best.sibling_path):
            best = record
    if best is None:
        return None
    return ValueAuthorship(
        path=path,
        source_kind=best.source_kind,
        source_path=best.source_path,
        source_order=best.source_order,
        composition_stage="file_include_local_customization",
        details={
            "include_site_path": list(best.include_site_path),
            "sibling_path": list(best.sibling_path),
            "customization_kind": best.kind,
        },
    )


def _authorship_from_recipe_manifest(
    *,
    path: ConfigPath,
    recipe_manifest: Sequence[Mapping[str, PlainData]],
) -> ValueAuthorship | None:
    best_record: Mapping[str, PlainData] | None = None
    best_path: ConfigPath = ()
    for record in recipe_manifest:
        record_path = record.get("path")
        if not isinstance(record_path, str):
            continue
        parsed_path = _path_from_config_string(record_path)
        if path[: len(parsed_path)] != parsed_path:
            continue
        if best_record is None or len(parsed_path) > len(best_path):
            best_record = record
            best_path = parsed_path
    if best_record is None:
        return None
    expanded_hash = best_record.get("expanded_hash")
    name = best_record.get("name")
    target = best_record.get("target")
    return ValueAuthorship(
        path=path,
        source_kind="recipe",
        source_path=str(best_record.get("expanded_path") or best_record.get("path") or "recipe"),
        source_order=0,
        source_content_digest=expanded_hash if isinstance(expanded_hash, str) else None,
        source_size_bytes=len(expanded_hash) if isinstance(expanded_hash, str) else None,
        composition_stage="recipe_expansion",
        details={
            "recipe_path": list(best_path),
            "recipe_name": name if isinstance(name, str) else "",
            "recipe_target": target if isinstance(target, str) else "",
        },
    )


def _authorship_from_ordinary_overrides(
    *,
    path: ConfigPath,
    ordinary_overrides: Sequence[ParsedOverride],
) -> ValueAuthorship | None:
    best: ParsedOverride | None = None
    best_path: ConfigPath = ()
    for override in ordinary_overrides:
        override_path = _path_from_override(override.path)
        if path[: len(override_path)] != override_path:
            continue
        if best is None or (len(override_path), override.order) >= (len(best_path), best.order):
            best = override
            best_path = override_path
    if best is None:
        return None
    return ValueAuthorship(
        path=path,
        source_kind="ordinary_override",
        source_path="<override>",
        source_order=best.order,
        composition_stage="ordinary_overrides",
        details={
            "override_path": best.path,
            "override_order": best.order,
            "override_operation": best.operation,
            "override_redacted": _override_is_redacted(best),
        },
    )


def _path_from_override(path: str) -> ConfigPath:
    return tuple(path.split("."))


def _path_from_config_string(path: str) -> ConfigPath:
    trimmed = path[2:] if path.startswith("$.") else path
    if trimmed == "$" or not trimmed:
        return ()
    return tuple(segment for segment in trimmed.split(".") if segment)


def _build_include_source_artifacts(
    *,
    include_sites: Sequence[IncludeSiteRecord],
    start_order: int,
) -> tuple[SourceArtifactRecord, ...]:
    artifacts: list[SourceArtifactRecord] = []
    for offset, record in enumerate(include_sites):
        artifacts.append(
            SourceArtifactRecord(
                schema_version=ARTIFACT_SCHEMA_VERSION,
                kind="include",
                path=record.resolved_path,
                order=start_order + offset,
                content_digest=record.included_content_digest,
                size_bytes=record.included_size_bytes,
                metadata={
                    "include_site_path": list(record.include_site_path),
                    "authored_target": record.authored_target,
                    "source_path": record.source_path,
                    "source_kind": record.source_kind,
                    "source_order": record.source_order,
                    "source_content_digest": record.source_content_digest,
                    "source_size_bytes": record.source_size_bytes,
                    "target_kind": record.target_kind,
                    "explicit_escape": record.explicit_escape,
                    "has_replace_marker": record.has_replace_marker,
                    "resolved_path": record.resolved_path,
                    "source_include_site_path": list(record.source_include_site_path),
                    "raw_snapshot": _metadata_only_raw_snapshot_limits(source_kind="include"),
                },
            )
        )
    return tuple(artifacts)


def _build_recipe_source_artifacts(
    *,
    recipe_manifest: Sequence[Mapping[str, PlainData]],
    start_order: int,
) -> tuple[SourceArtifactRecord, ...]:
    artifacts: list[SourceArtifactRecord] = []
    for offset, manifest_record in enumerate(recipe_manifest):
        expanded_hash = cast(str | None, manifest_record.get("expanded_hash"))
        expanded_path = cast(str | None, manifest_record.get("expanded_path"))
        name = manifest_record.get("name")
        path = manifest_record.get("path")
        target = manifest_record.get("target")
        if not isinstance(expanded_hash, str) or not expanded_hash:
            continue
        artifact_path = expanded_path if isinstance(expanded_path, str) and expanded_path else f"recipe:{offset}"
        artifacts.append(
            SourceArtifactRecord(
                schema_version=ARTIFACT_SCHEMA_VERSION,
                kind="recipe",
                path=artifact_path,
                order=start_order + offset,
                content_digest=expanded_hash,
                size_bytes=len(expanded_hash),
                metadata={
                    "name": cast(str, name) if isinstance(name, str) else "",
                    "path": cast(str, path) if isinstance(path, str) else artifact_path,
                    "target": cast(str, target) if isinstance(target, str) else "",
                    "expanded_hash": expanded_hash,
                    "loom_version": manifest_record.get("loom_version"),
                    "raw_snapshot": _metadata_only_raw_snapshot_limits(source_kind="recipe"),
                },
            )
        )
    return tuple(artifacts)


def _metadata_only_raw_snapshot_limits(*, source_kind: str) -> dict[str, PlainData]:
    reason = "unsupported_source_kind" if source_kind == "recipe" else "not_requested"
    availability = "unavailable" if source_kind == "recipe" else "disabled"
    return {
        "content_in_source_artifact": False,
        "manifest_embeds_content": False,
        "availability_without_opt_in": availability,
        "reason_without_opt_in": reason,
        "rebuild_limitation": "metadata_hash_only_without_raw_snapshot_bundle",
    }


def _to_source_artifact_reference(record: SourceArtifactRecord) -> dict[str, PlainData]:
    return {
        "kind": record.kind,
        "order": record.order,
        "path": record.path,
        "content_digest": record.content_digest,
        "size_bytes": record.size_bytes,
    }


def _build_provenance_metadata(
    *,
    include_records: Sequence[IncludeSiteRecord],
    recomposition_contexts: Sequence[IncludeRecompositionContext],
    local_customizations: Sequence[IncludeLocalCustomization],
    include_overrides: Sequence[ParsedOverride],
    ordinary_overrides: Sequence[ParsedOverride],
    recipe_manifest: Sequence[Mapping[str, PlainData]],
    resolver_records: Sequence[ResolverExpressionRecord],
    source_artifacts: Sequence[SourceArtifactRecord],
    value_authorship: Mapping[ConfigPath, ValueAuthorship],
    redaction_policy: dict[str, PlainData],
    warnings: tuple[dict[str, PlainData], ...],
    raw_source_snapshot_references: Sequence[dict[str, PlainData]],
) -> dict[str, PlainData]:
    redacted_include_overrides = [
        _override_to_dict(override, record_values=True) for override in include_overrides
    ]
    redacted_ordinary_overrides = [
        _override_to_dict(override, record_values=True) for override in ordinary_overrides
    ]

    metadata = {
        "provenance_version": PROVENANCE_SCHEMA_VERSION,
        "source_fact_records": {
            "sources": [source.to_dict() for source in source_artifacts],
            "include_sites": [record.to_dict() for record in include_records],
            "include_recomposition_contexts": [context.to_dict() for context in recomposition_contexts],
            "local_customizations": [record.to_dict() for record in local_customizations],
            "final_value_authorship": [
                value_authorship[path].to_dict() for path in sorted(value_authorship, key=format_config_path)
            ],
        },
        "include_overrides": redacted_include_overrides,
        "ordinary_overrides": redacted_ordinary_overrides,
        "user_composition_override_count": len(include_overrides),
        "ordinary_override_count": len(ordinary_overrides),
        "recipe_manifest": [_ensure_mappingproxy_plain(record) for record in recipe_manifest],
        "resolver_records": [
            {
                "config_path": record.config_path,
                "token": record.token,
                "resolver": record.resolver,
                "expression": record.expression,
            }
            for record in resolver_records
        ],
        "source_artifact_references": [
            _to_source_artifact_reference(record) for record in source_artifacts
        ],
        "raw_source_snapshot_references": list(raw_source_snapshot_references),
        "redaction_policy": redaction_policy,
        "security_facts": {
            "artifact_safety": {
                "raw_source_bytes_included": False,
                "resolved_runtime_values_included": False,
            },
            "redaction_marker": REDACTION_MARKER,
            "plaintext_secret_override_warnings": list(warnings),
            "resolver_policy": "artifact_safe_runtime_resolve",
        },
        "schema_version": ARTIFACT_SCHEMA_VERSION,
    }
    return cast(dict[str, PlainData], to_plain_data(metadata, path="provenance_metadata"))


def _plaintext_secret_warnings(overrides: Sequence[ParsedOverride]) -> tuple[dict[str, PlainData], ...]:
    warnings: list[dict[str, PlainData]] = []
    for override in overrides:
        if not _override_is_redacted(override):
            continue

        warnings.append(
            {
                "warning_type": "plaintext_secret_override",
                "override_path": override.path,
                "override_operation": override.operation,
                "override_order": override.order,
                "override_raw": REDACTION_MARKER,
                "redacted": True,
            }
        )

    return tuple(warnings)


def _override_to_dict(override: ParsedOverride, *, record_values: bool = False) -> dict[str, PlainData]:
    value: PlainData = cast(PlainData, override.value)
    final_key = override.path.rsplit(".", 1)[-1]
    redacted = _override_is_redacted(override)
    if is_secret_path(override.path):
        value = REDACTION_MARKER
    elif redacted or record_values:
        value = redact_secret_like_value(final_key, value)

    return {
        "raw": REDACTION_MARKER if redacted else override.raw,
        "path": override.path,
        "operation": override.operation,
        "value": value,
        "order": override.order,
        "redacted": redacted,
    }

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
