"""Internal source-map helpers for config composition."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from loom.serialization import PlainData, ensure_plain_data

from .errors import ConfigMergeError
from .provenance import ConfigSource

ConfigPathSegment = str | int
ConfigPath = tuple[ConfigPathSegment, ...]

_REPLACE_KEY = "_replace_"


@dataclass(frozen=True, slots=True)
class ComposedConfigWithSources:
    """Result payload for source-aware config composition."""

    config: dict[str, PlainData]
    source_map: dict[ConfigPath, ConfigSource]


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

    merged = normalized_base
    for overlay_config, overlay_source in overlays:
        if not isinstance(overlay_config, Mapping):
            raise ConfigMergeError("Invalid overlay mapping at $")
        merged = _merge_with_sources(
            base=merged,
            overlay=overlay_config,
            path=(),
            source=overlay_source,
            source_map=source_map,
        )

    return ComposedConfigWithSources(config=merged, source_map=source_map)


def build_base_source_map(
    mapping: Mapping[str, PlainData],
    source: ConfigSource,
) -> dict[ConfigPath, ConfigSource]:
    """Build a source map for a concrete loaded config value."""

    if not isinstance(mapping, Mapping):
        raise ConfigMergeError("Invalid base mapping at $")

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
) -> dict[str, PlainData]:
    if not isinstance(base, Mapping):
        raise ConfigMergeError(f"Invalid base mapping at {_format_config_path(path)}")
    if not isinstance(overlay, Mapping):
        raise ConfigMergeError(f"Invalid overlay mapping at {_format_config_path(path)}")

    merged = {key: _normalize_mapping_value(value, path=f"{_format_config_path(path)}[{key!r}]") for key, value in base.items()}

    if _REPLACE_KEY in overlay:
        return _merge_replace_mapping_with_sources(
            base_value=merged,
            overlay_value=overlay,
            path=path,
            source=source,
            source_map=source_map,
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
        )

    return merged


def _merge_value_with_sources(
    *,
    base_value: PlainData | None,
    overlay_value: PlainData,
    path: ConfigPath,
    source: ConfigSource,
    source_map: dict[ConfigPath, ConfigSource],
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
            )

        if isinstance(base_value, dict):
            source_map[path] = source
            return _merge_with_sources(
                base=base_value,
                overlay=overlay_mapping,
                path=path,
                source=source,
                source_map=source_map,
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
) -> dict[str, PlainData]:
    if not isinstance(base_value, Mapping):
        raise ConfigMergeError(
            f"Invalid _replace_ usage at {_format_config_path(path)}: expected an existing mapping to replace",
        )

    replace_marker = overlay_value.get(_REPLACE_KEY)
    if replace_marker is not True:
        raise ConfigMergeError(f"Invalid _replace_ value at {_format_config_path(path)}: expected true")

    replacement_value: dict[str, PlainData] = {key: value for key, value in overlay_value.items() if key != _REPLACE_KEY}
    if not replacement_value:
        raise ConfigMergeError(f"Invalid _replace_ usage at {_format_config_path(path)}: no replacement keys provided")

    _remove_path_and_descendants(source_map, path)
    source_map[path] = source

    base_mapping = cast(dict[str, PlainData], base_value)
    merged: dict[str, PlainData] = {}
    for key, overlay_raw_value in replacement_value.items():
        child_path = path + (key,)
        overlay_child = _normalize_mapping_value(
            overlay_raw_value,
            path=f"{_format_config_path(child_path)}",
        )
        merged[key] = _merge_value_with_sources(
            base_value=base_mapping.get(key),
            overlay_value=overlay_child,
            path=child_path,
            source=source,
            source_map=source_map,
        )

    return merged


def _normalize_mapping_value(value: object, path: str) -> PlainData:
    try:
        return ensure_plain_data(value, path=path)
    except Exception as exc:  # noqa: BLE001
        raise ConfigMergeError(f"Invalid config value at {path}") from exc
