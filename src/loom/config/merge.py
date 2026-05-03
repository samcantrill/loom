"""Recursive config merge helpers."""

from __future__ import annotations

from collections.abc import Mapping

from loom.serialization import PlainData, ensure_plain_data

from .errors import ConfigMergeError


def merge_configs(
    base: Mapping[str, PlainData],
    overlay: Mapping[str, PlainData],
    *,
    path: str = "$",
) -> dict[str, PlainData]:
    """Merge two config mappings with right-hand override semantics."""

    if not isinstance(base, Mapping):
        raise ConfigMergeError(f"Invalid base mapping at {path}")
    if not isinstance(overlay, Mapping):
        raise ConfigMergeError(f"Invalid overlay mapping at {path}")

    merged: dict[str, PlainData] = {}

    for key in base:
        merged[key] = _normalize_mapping_value(base[key], path=f"{path}[{key!r}]")

    for key, overlay_value in overlay.items():
        base_value = merged.get(key)
        if isinstance(base_value, Mapping) and isinstance(overlay_value, Mapping):
            merged[key] = merge_configs(
                base_value,
                overlay_value,
                path=f"{path}[{key!r}]",
            )
            continue
        merged[key] = _normalize_mapping_value(overlay_value, path=f"{path}[{key!r}]")

    return merged


def _normalize_mapping_value(value: object, path: str) -> PlainData:
    try:
        return ensure_plain_data(value, path=path)
    except Exception as exc:  # noqa: BLE001
        raise ConfigMergeError(f"Invalid config value at {path}") from exc
