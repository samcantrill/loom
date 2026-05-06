"""Recursive config merge helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from loom.serialization import PlainData, ensure_plain_data

from .errors import ConfigErrorContext, ConfigMergeError


def merge_configs(
    base: Mapping[str, PlainData],
    overlay: Mapping[str, PlainData],
    *,
    path: str = "$",
) -> dict[str, PlainData]:
    """Merge two config mappings with right-hand override semantics."""
    if not isinstance(base, Mapping):
        raise _merge_error(
            f"Invalid base mapping at {path}",
            code="invalid_base_mapping",
            path=path,
            expected="mapping",
            actual=type(base).__name__,
        )
    if not isinstance(overlay, Mapping):
        raise _merge_error(
            f"Invalid overlay mapping at {path}",
            code="invalid_overlay_mapping",
            path=path,
            expected="mapping",
            actual=type(overlay).__name__,
        )

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
        raise _merge_error(
            f"Invalid _replace_ usage at {path}: expected an existing mapping to replace",
            code="replace_target_not_mapping",
            path=path,
            directive=_REPLACE_KEY,
            expected="existing mapping",
            actual=type(base_value).__name__ if base_value is not None else "missing",
            details={"reason": "replace_requires_existing_mapping"},
        )

    replace_marker = overlay_value.get(_REPLACE_KEY)
    if replace_marker is not True:
        raise _merge_error(
            f"Invalid _replace_ value at {path}: expected true",
            code="invalid_replace_value",
            path=path,
            directive=_REPLACE_KEY,
            expected=True,
            actual=replace_marker,
            details={"reason": "replace_marker_must_be_true"},
        )

    replacement_value: dict[str, PlainData] = {
        key: value for key, value in overlay_value.items() if key != _REPLACE_KEY
    }
    if not replacement_value:
        raise _merge_error(
            f"Invalid _replace_ usage at {path}: no replacement keys provided",
            code="empty_replace_mapping",
            path=path,
            directive=_REPLACE_KEY,
            expected="one or more replacement keys",
            actual="empty replacement mapping",
            details={"reason": "replace_requires_sibling_keys"},
        )

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
        raise _merge_error(
            f"Invalid config value at {path}",
            code="non_plain_config_value",
            path=path,
            expected="plain data",
            actual=type(value).__name__,
        ) from exc


_REPLACE_KEY = "_replace_"


def _merge_error(
    message: str,
    *,
    code: str,
    path: str,
    expected: object | None = None,
    actual: object | None = None,
    directive: str | None = None,
    details: dict[str, object] | None = None,
) -> ConfigMergeError:
    return ConfigMergeError(
        message,
        context=ConfigErrorContext(
            code=code,
            source_kind="merge",
            source_order=-1,
            source_path="<merge>",
            config_path=path,
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
