"""Recursive config merge helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

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

    merged: dict[str, PlainData] = {
        key: _normalize_mapping_value(value, path=f"{path}[{key!r}]") for key, value in base.items()
    }

    if _REPLACE_KEY in overlay:
        return _merge_replace_mapping(base_value=merged, overlay_value=overlay, path=path)

    for key, overlay_raw_value in overlay.items():
        child_path = f"{path}[{key!r}]"
        base_value = merged.get(key)
        overlay_value = _normalize_mapping_value(overlay_raw_value, path=child_path)
        merged[key] = _merge_values(base_value=base_value, overlay_value=overlay_value, path=child_path)

    return merged


def _merge_values(
    *,
    base_value: PlainData | None,
    overlay_value: PlainData,
    path: str,
) -> PlainData:
    if isinstance(overlay_value, Mapping):
        overlay_mapping = cast(dict[str, PlainData], overlay_value)
        if _REPLACE_KEY in overlay_mapping:
            return _merge_replace_mapping(
                base_value=base_value,
                overlay_value=overlay_mapping,
                path=path,
            )

    if isinstance(base_value, Mapping) and isinstance(overlay_value, Mapping):
        return merge_configs(base_value, overlay_value, path=path)

    return overlay_value


def _merge_replace_mapping(
    *,
    base_value: PlainData | None,
    overlay_value: Mapping[str, PlainData],
    path: str,
) -> dict[str, PlainData]:
    if not isinstance(base_value, Mapping):
        raise ConfigMergeError(f"Invalid _replace_ usage at {path}: expected an existing mapping to replace")

    replace_marker = overlay_value.get(_REPLACE_KEY)
    if replace_marker is not True:
        raise ConfigMergeError(f"Invalid _replace_ value at {path}: expected true")

    replacement_value: dict[str, PlainData] = {
        key: value for key, value in overlay_value.items() if key != _REPLACE_KEY
    }
    if not replacement_value:
        raise ConfigMergeError(f"Invalid _replace_ usage at {path}: no replacement keys provided")

    return {
        key: _normalize_replacement_value(
            value,
            base_value=base_value.get(key),
            path=f"{path}[{key!r}]",
        )
        for key, value in replacement_value.items()
    }


def _normalize_replacement_value(
    value: object,
    *,
    base_value: PlainData | None,
    path: str,
) -> PlainData:
    replacement_value = _normalize_mapping_value(value, path=path)
    if not isinstance(replacement_value, Mapping):
        return replacement_value

    replacement_mapping = cast(dict[str, PlainData], replacement_value)
    if _REPLACE_KEY in replacement_mapping:
        return _merge_replace_mapping(
            base_value=base_value,
            overlay_value=replacement_mapping,
            path=path,
        )

    base_mapping = base_value if isinstance(base_value, Mapping) else {}
    return {
        key: _normalize_replacement_value(
            child_value,
            base_value=base_mapping.get(key),
            path=f"{path}[{key!r}]",
        )
        for key, child_value in replacement_mapping.items()
    }


def _normalize_mapping_value(value: object, path: str) -> PlainData:
    try:
        return ensure_plain_data(value, path=path)
    except Exception as exc:  # noqa: BLE001
        raise ConfigMergeError(f"Invalid config value at {path}") from exc


_REPLACE_KEY = "_replace_"
