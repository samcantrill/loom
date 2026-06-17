"""Internal source-map helpers for config composition."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, cast

from .plain import PlainData, ensure_plain_data

from .errors import ConfigErrorContext, ConfigMergeError
from .provenance import ConfigSource

ConfigPathSegment = str | int
ConfigPath = tuple[ConfigPathSegment, ...]

_REPLACE_KEY = "_replace_"


@dataclass(frozen=True, slots=True)
class ComposedConfigWithSources:
    """Result payload for source-aware config composition."""

    config: dict[str, PlainData]
    source_map: dict[ConfigPath, ConfigSource]
    replacement_sites: tuple[ConfigPath, ...]
    mapping_sites: tuple[ConfigPath, ...]


@dataclass(frozen=True, slots=True)
class ValueAuthorship:
    """Metadata-only record for the source that authored a final config value."""

    path: ConfigPath
    source_kind: str
    source_path: str
    source_order: int
    composition_stage: str
    source_content_digest: str | None = None
    source_size_bytes: int | None = None
    details: dict[str, PlainData] | None = None

    def to_dict(self) -> dict[str, PlainData]:
        payload: dict[str, PlainData] = {
            "config_path": format_config_path(self.path),
            "path": [segment for segment in self.path],
            "source_kind": self.source_kind,
            "source_path": self.source_path,
            "source_order": self.source_order,
            "composition_stage": self.composition_stage,
        }
        if self.source_content_digest is not None:
            payload["source_content_digest"] = self.source_content_digest
        if self.source_size_bytes is not None:
            payload["source_size_bytes"] = self.source_size_bytes
        if self.details:
            details = ensure_plain_data(self.details, path=f"authorship[{format_config_path(self.path)}].details")
            if not isinstance(details, dict):
                raise TypeError("ValueAuthorship details must be a mapping")
            payload["details"] = details
        return payload


def compose_config_with_sources(
    *,
    base_config: Mapping[str, PlainData],
    base_source: ConfigSource,
    overlays: Sequence[tuple[Mapping[str, PlainData], ConfigSource]],
) -> ComposedConfigWithSources:
    """Compose loaded base and overlay configs while tracking node authorship."""

    normalized_base = {
        key: _normalize_mapping_value(value, path=_format_config_path((key,))) for key, value in base_config.items()
    }
    source_map = build_base_source_map(normalized_base, base_source)
    replacement_sites: list[ConfigPath] = []
    mapping_sites: list[ConfigPath] = []
    if overlays:
        mapping_sites.append(())

    merged = normalized_base
    for overlay_config, overlay_source in overlays:
        if not isinstance(overlay_config, Mapping):
            raise _source_merge_error(
                "Invalid overlay mapping at $",
                code="invalid_overlay_mapping",
                path=(),
                source=overlay_source,
                expected="mapping",
                actual=type(overlay_config).__name__,
            )
        merged = _merge_with_sources(
            base=merged,
            overlay=overlay_config,
            path=(),
            source=overlay_source,
            source_map=source_map,
            replacement_sites=replacement_sites,
            mapping_sites=mapping_sites,
        )

    return ComposedConfigWithSources(
        config=merged,
        source_map=source_map,
        replacement_sites=tuple(replacement_sites),
        mapping_sites=tuple(mapping_sites),
    )



def apply_scoped_overlay_with_sources(
    composed: ComposedConfigWithSources,
    *,
    overlay: Mapping[str, PlainData],
    source: ConfigSource,
    scope_path: ConfigPath,
    operation: Literal["update", "add"],
    details: Mapping[str, PlainData] | None = None,
) -> ComposedConfigWithSources:
    """Apply one scoped overlay while preserving source-map authorship."""

    if not scope_path:
        raise _scoped_overlay_error(
            "Scoped overlays must target a non-root path.",
            code="invalid_scoped_overlay_root",
            path=scope_path,
            source=source,
            details=details,
        )
    if operation not in {"update", "add"}:
        raise _scoped_overlay_error(
            "Scoped overlay operation must be update or add.",
            code="invalid_scoped_overlay_operation",
            path=scope_path,
            source=source,
            expected="update or add",
            actual=operation,
            details=details,
        )
    if not isinstance(overlay, Mapping):
        raise _scoped_overlay_error(
            "Scoped overlay source root must be a mapping.",
            code="scoped_overlay_root_not_mapping",
            path=scope_path,
            source=source,
            expected="mapping",
            actual=type(overlay).__name__,
            details=details,
        )

    staged = {
        key: _normalize_mapping_value(value, path=_format_config_path((key,)))
        for key, value in composed.config.items()
    }
    source_map = dict(composed.source_map)
    replacement_sites = list(composed.replacement_sites)
    mapping_sites = list(composed.mapping_sites)
    overlay_mapping = {
        key: _normalize_mapping_value(value, path=f"{_format_config_path(scope_path)}[{key!r}]")
        for key, value in overlay.items()
    }

    parent, key, created_parent_paths = _ensure_scoped_overlay_parent(
        config=staged,
        path=scope_path,
        source=source,
        operation=operation,
        details=details,
    )
    for created_path in created_parent_paths:
        source_map[created_path] = source
        if created_path not in mapping_sites:
            mapping_sites.append(created_path)

    target_exists = key in parent
    if operation == "update" and not target_exists:
        raise _scoped_overlay_error(
            "Cannot update a missing scoped overlay target.",
            code="missing_scoped_overlay_target",
            path=scope_path,
            source=source,
            expected="existing target",
            actual="missing",
            details=details,
        )
    if operation == "add" and target_exists:
        raise _scoped_overlay_error(
            "Cannot add a scoped overlay at an existing target.",
            code="existing_scoped_overlay_target",
            path=scope_path,
            source=source,
            expected="missing target",
            actual="existing",
            details=details,
        )

    base_value = parent.get(key)
    if target_exists and isinstance(base_value, Mapping):
        if scope_path not in mapping_sites:
            mapping_sites.append(scope_path)
        source_map[scope_path] = source
        merged_value = _merge_with_sources(
            base=cast(Mapping[str, PlainData], base_value),
            overlay=overlay_mapping,
            path=scope_path,
            source=source,
            source_map=source_map,
            replacement_sites=replacement_sites,
            mapping_sites=mapping_sites,
        )
    else:
        if "_replace_" in overlay_mapping:
            merged_value = _merge_replace_mapping_with_sources(
                base_value=base_value,
                overlay_value=overlay_mapping,
                path=scope_path,
                source=source,
                source_map=source_map,
                replacement_sites=replacement_sites,
                mapping_sites=mapping_sites,
            )
        else:
            merged_value = dict(overlay_mapping)
            _set_value_source(source_map, path=scope_path, value=merged_value, source=source)
            if scope_path not in mapping_sites:
                mapping_sites.append(scope_path)

    parent[key] = cast(PlainData, merged_value)
    return ComposedConfigWithSources(
        config=staged,
        source_map=source_map,
        replacement_sites=tuple(replacement_sites),
        mapping_sites=tuple(mapping_sites),
    )


def _ensure_scoped_overlay_parent(
    *,
    config: dict[str, PlainData],
    path: ConfigPath,
    source: ConfigSource,
    operation: Literal["update", "add"],
    details: Mapping[str, PlainData] | None,
) -> tuple[dict[str, PlainData], str, tuple[ConfigPath, ...]]:
    parent = config
    created_paths: list[ConfigPath] = []
    for index, segment in enumerate(path[:-1]):
        current_path = path[: index + 1]
        if not isinstance(segment, str):
            raise _scoped_overlay_error(
                "Scoped overlay path segments must be strings.",
                code="invalid_scoped_overlay_path_segment",
                path=current_path,
                source=source,
                expected="string path segment",
                actual=type(segment).__name__,
                details=details,
            )
        child = parent.get(segment)
        if child is None:
            if operation != "add":
                raise _scoped_overlay_error(
                    "Cannot update a scoped overlay through a missing parent.",
                    code="missing_scoped_overlay_parent",
                    path=current_path,
                    source=source,
                    expected="existing mapping parent",
                    actual="missing",
                    details=details,
                )
            new_child: dict[str, PlainData] = {}
            parent[segment] = new_child
            parent = new_child
            created_paths.append(current_path)
            continue
        if not isinstance(child, dict):
            raise _scoped_overlay_error(
                "Cannot apply a scoped overlay through a non-mapping parent.",
                code="non_mapping_scoped_overlay_parent",
                path=current_path,
                source=source,
                expected="mapping parent",
                actual=type(child).__name__,
                details=details,
            )
        parent = child

    final_key = path[-1]
    if not isinstance(final_key, str):
        raise _scoped_overlay_error(
            "Scoped overlay final path segment must be a string.",
            code="invalid_scoped_overlay_path_segment",
            path=path,
            source=source,
            expected="string path segment",
            actual=type(final_key).__name__,
            details=details,
        )
    return parent, final_key, tuple(created_paths)


def _scoped_overlay_error(
    message: str,
    *,
    code: str,
    path: ConfigPath,
    source: ConfigSource,
    expected: object | None = None,
    actual: object | None = None,
    details: Mapping[str, PlainData] | None = None,
) -> ConfigMergeError:
    payload: dict[str, PlainData] = {
        "scope_path": [segment for segment in path],
        **dict(details or {}),
    }
    return ConfigMergeError(
        message,
        context=ConfigErrorContext(
            code=code,
            source_kind="argv_scoped_overlay",
            source_order=source.order,
            source_path=source.path,
            config_path=format_config_path(path),
            expected=ensure_plain_data(expected) if expected is not None else None,
            actual=ensure_plain_data(actual) if actual is not None else None,
            directive="argv_scoped_overlay",
            remediation=_scoped_overlay_remediation(code),
            details=cast(dict[str, PlainData], ensure_plain_data(payload)),
        ),
    )


def _scoped_overlay_remediation(code: str) -> str | None:
    if code == "missing_scoped_overlay_target":
        return "Use +scope/=... for new scoped overlay targets, or target an existing path."
    if code == "existing_scoped_overlay_target":
        return "Use update scoped overlay syntax for existing targets."
    if code in {"missing_scoped_overlay_parent", "non_mapping_scoped_overlay_parent"}:
        return "Choose a mapping parent path for the scoped overlay target."
    if code == "invalid_scoped_overlay_root":
        return "Use the base config path for root config selection; scoped overlays must target a non-root scope."
    return None

def build_base_source_map(
    mapping: Mapping[str, PlainData],
    source: ConfigSource,
) -> dict[ConfigPath, ConfigSource]:
    """Build a source map for a concrete loaded config value."""

    if not isinstance(mapping, Mapping):
        raise _source_merge_error(
            "Invalid base mapping at $",
            code="invalid_base_mapping",
            path=(),
            source=source,
            expected="mapping",
            actual=type(mapping).__name__,
        )

    normalized = {
        key: _normalize_mapping_value(value, path=_format_config_path((key,))) for key, value in mapping.items()
    }
    source_map: dict[ConfigPath, ConfigSource] = {}
    _record_value_source(source_map, path=(), value=normalized, source=source)
    return source_map


def format_config_path(path: ConfigPath) -> str:
    """Format immutable path tuples into human-readable diagnostics."""

    if not path:
        return "$"

    rendered = "$"
    for segment in path:
        if isinstance(segment, int):
            rendered += f"[{segment}]"
            continue

        if segment.isidentifier():
            rendered += f".{segment}"
            continue

        escaped = segment.replace("\\", r"\\").replace("'", r"\'")
        rendered += f"['{escaped}']"

    return rendered


def _format_config_path(path: ConfigPath) -> str:
    """Compatibility helper for compatibility with merge-style diagnostics."""

    return format_config_path(path)


def _remove_path_and_descendants(source_map: dict[ConfigPath, ConfigSource], path: ConfigPath) -> None:
    path_length = len(path)
    for existing_path in tuple(source_map):
        if existing_path[:path_length] == path:
            del source_map[existing_path]


def _record_value_source(
    source_map: dict[ConfigPath, ConfigSource],
    *,
    path: ConfigPath,
    value: PlainData,
    source: ConfigSource,
) -> None:
    source_map[path] = source
    if isinstance(value, dict):
        for key, child in value.items():
            _record_value_source(
                source_map,
                path=path + (key,),
                value=cast(dict[str, PlainData], child) if isinstance(child, dict) else cast(PlainData, child),
                source=source,
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _record_value_source(source_map, path=path + (index,), value=cast(PlainData, child), source=source)


def _set_value_source(
    source_map: dict[ConfigPath, ConfigSource],
    *,
    path: ConfigPath,
    value: PlainData,
    source: ConfigSource,
) -> None:
    _remove_path_and_descendants(source_map, path)
    _record_value_source(source_map, path=path, value=value, source=source)


def _merge_with_sources(
    base: Mapping[str, PlainData],
    overlay: Mapping[str, PlainData],
    *,
    path: ConfigPath,
    source: ConfigSource,
    source_map: dict[ConfigPath, ConfigSource],
    replacement_sites: list[ConfigPath],
    mapping_sites: list[ConfigPath],
) -> dict[str, PlainData]:
    if not isinstance(base, Mapping):
        raise _source_merge_error(
            f"Invalid base mapping at {_format_config_path(path)}",
            code="invalid_base_mapping",
            path=path,
            source=source,
            expected="mapping",
            actual=type(base).__name__,
        )
    if not isinstance(overlay, Mapping):
        raise _source_merge_error(
            f"Invalid overlay mapping at {_format_config_path(path)}",
            code="invalid_overlay_mapping",
            path=path,
            source=source,
            expected="mapping",
            actual=type(overlay).__name__,
        )

    merged = {
        key: _normalize_mapping_value(value, path=f"{_format_config_path(path)}[{key!r}]")
        for key, value in base.items()
    }

    if _REPLACE_KEY in overlay:
        return _merge_replace_mapping_with_sources(
            base_value=merged,
            overlay_value=overlay,
            path=path,
            source=source,
            source_map=source_map,
            replacement_sites=replacement_sites,
            mapping_sites=mapping_sites,
        )

    for key, overlay_raw_value in overlay.items():
        child_path = path + (key,)
        overlay_value = _normalize_mapping_value(overlay_raw_value, path=f"{_format_config_path(child_path)}")
        merged[key] = _merge_value_with_sources(
            base_value=merged.get(key),
            overlay_value=overlay_value,
            path=child_path,
            source=source,
            source_map=source_map,
            replacement_sites=replacement_sites,
            mapping_sites=mapping_sites,
        )

    return merged


def _merge_value_with_sources(
    *,
    base_value: PlainData | None,
    overlay_value: PlainData,
    path: ConfigPath,
    source: ConfigSource,
    source_map: dict[ConfigPath, ConfigSource],
    replacement_sites: list[ConfigPath],
    mapping_sites: list[ConfigPath],
) -> PlainData:
    if isinstance(overlay_value, dict):
        overlay_mapping = cast(dict[str, PlainData], overlay_value)
        if _REPLACE_KEY in overlay_mapping:
            return _merge_replace_mapping_with_sources(
                base_value=base_value,
                overlay_value=overlay_mapping,
                path=path,
                source=source,
                source_map=source_map,
                replacement_sites=replacement_sites,
                mapping_sites=mapping_sites,
            )

        if isinstance(base_value, dict):
            mapping_sites.append(path)
            source_map[path] = source
            return _merge_with_sources(
                base=base_value,
                overlay=overlay_mapping,
                path=path,
                source=source,
                source_map=source_map,
                replacement_sites=replacement_sites,
                mapping_sites=mapping_sites,
            )

    _set_value_source(source_map, path=path, value=overlay_value, source=source)
    return overlay_value


def _merge_replace_mapping_with_sources(
    *,
    base_value: PlainData | None,
    overlay_value: Mapping[str, PlainData],
    path: ConfigPath,
    source: ConfigSource,
    source_map: dict[ConfigPath, ConfigSource],
    replacement_sites: list[ConfigPath],
    mapping_sites: list[ConfigPath],
) -> dict[str, PlainData]:
    if not isinstance(base_value, Mapping):
        raise _source_merge_error(
            f"Invalid _replace_ usage at {_format_config_path(path)}: expected an existing mapping to replace",
            code="replace_target_not_mapping",
            path=path,
            source=source,
            directive=_REPLACE_KEY,
            expected="existing mapping",
            actual=type(base_value).__name__ if base_value is not None else "missing",
            details={"reason": "replace_requires_existing_mapping"},
        )

    replace_marker = overlay_value.get(_REPLACE_KEY)
    if replace_marker is not True:
        raise _source_merge_error(
            f"Invalid _replace_ value at {_format_config_path(path)}: expected true",
            code="invalid_replace_value",
            path=path,
            source=source,
            directive=_REPLACE_KEY,
            expected=True,
            actual=replace_marker,
            details={"reason": "replace_marker_must_be_true"},
        )

    replacement_sites.append(path)

    replacement_value: dict[str, PlainData] = {
        key: value for key, value in overlay_value.items() if key != _REPLACE_KEY
    }
    if not replacement_value:
        raise _source_merge_error(
            f"Invalid _replace_ usage at {_format_config_path(path)}: no replacement keys provided",
            code="empty_replace_mapping",
            path=path,
            source=source,
            directive=_REPLACE_KEY,
            expected="one or more replacement keys",
            actual="empty replacement mapping",
            details={"reason": "replace_requires_sibling_keys"},
        )

    _remove_path_and_descendants(source_map, path)
    source_map[path] = source

    base_mapping = cast(dict[str, PlainData], base_value)
    merged: dict[str, PlainData] = {}
    for key, overlay_raw_value in replacement_value.items():
        child_path = path + (key,)
        merged[key] = _normalize_replacement_value_with_sources(
            overlay_raw_value,
            base_value=base_mapping.get(key),
            path=child_path,
            source=source,
            source_map=source_map,
            replacement_sites=replacement_sites,
            mapping_sites=mapping_sites,
        )

    return merged


def _normalize_replacement_value_with_sources(
    value: object,
    *,
    base_value: PlainData | None,
    path: ConfigPath,
    source: ConfigSource,
    source_map: dict[ConfigPath, ConfigSource],
    replacement_sites: list[ConfigPath],
    mapping_sites: list[ConfigPath],
) -> PlainData:
    replacement_value = _normalize_mapping_value(value, path=_format_config_path(path))
    if not isinstance(replacement_value, dict):
        _set_value_source(source_map, path=path, value=replacement_value, source=source)
        return replacement_value

    replacement_mapping = cast(dict[str, PlainData], replacement_value)
    if _REPLACE_KEY in replacement_mapping:
        return _merge_replace_mapping_with_sources(
            base_value=base_value,
            overlay_value=replacement_mapping,
            path=path,
            source=source,
            source_map=source_map,
            replacement_sites=replacement_sites,
            mapping_sites=mapping_sites,
        )

    source_map[path] = source
    base_mapping = base_value if isinstance(base_value, Mapping) else {}
    merged: dict[str, PlainData] = {}
    for key, child_value in replacement_mapping.items():
        child_path = path + (key,)
        merged[key] = _normalize_replacement_value_with_sources(
            child_value,
            base_value=base_mapping.get(key),
            path=child_path,
            source=source,
            source_map=source_map,
            replacement_sites=replacement_sites,
            mapping_sites=mapping_sites,
        )

    return merged


def _normalize_mapping_value(value: object, path: str) -> PlainData:
    try:
        return ensure_plain_data(value, path=path)
    except Exception as exc:  # noqa: BLE001
        raise ConfigMergeError(
            f"Invalid config value at {path}",
            context=ConfigErrorContext(
                code="non_plain_config_value",
                source_kind="merge",
                source_order=-1,
                source_path="<merge>",
                config_path=path,
                expected="plain data",
                actual=type(value).__name__,
            ),
        ) from exc


def _source_merge_error(
    message: str,
    *,
    code: str,
    path: ConfigPath,
    source: ConfigSource,
    expected: object | None = None,
    actual: object | None = None,
    directive: str | None = None,
    details: dict[str, object] | None = None,
) -> ConfigMergeError:
    return ConfigMergeError(
        message,
        context=ConfigErrorContext(
            code=code,
            source_kind=source.kind,
            source_order=source.order,
            source_path=source.path,
            config_path=format_config_path(path),
            expected=ensure_plain_data(expected) if expected is not None else None,
            actual=ensure_plain_data(actual) if actual is not None else None,
            directive=directive,
            remediation=_merge_remediation(code),
            details=cast(dict[str, PlainData], ensure_plain_data(details or {})),
        ),
    )


def _merge_remediation(code: str) -> str | None:
    if code == "replace_target_not_mapping":
        return "Use _replace_: true only when replacing an existing mapping."
    if code == "invalid_replace_value":
        return "Set _replace_ to the boolean value true."
    if code == "empty_replace_mapping":
        return "Add sibling replacement keys beside _replace_: true."
    return None
