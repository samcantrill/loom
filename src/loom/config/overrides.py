"""Override parsing and application."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence

from loom.serialization import PlainData, ensure_plain_data
from loom.serialization.errors import PlainDataError

from .errors import ConfigErrorContext, OverrideApplyError, OverrideParseError
from .redaction import REDACTION_MARKER, contains_secret_like_value, is_secret_key
from .provenance import ParsedOverride

_FLOAT_RE = re.compile(r"^[+-]?(?:\d*\.\d+|\d+\.\d*|\d+)(?:[eE][+-]?\d+)?$")


def parse_overrides(overrides: Sequence[str]) -> tuple[ParsedOverride, ...]:
    return tuple(_parse_override(raw=raw, order=index) for index, raw in enumerate(overrides))


def split_include_and_ordinary_overrides(
    overrides: Sequence[ParsedOverride],
) -> tuple[tuple[ParsedOverride, ...], tuple[ParsedOverride, ...]]:
    include_overrides: list[ParsedOverride] = []
    ordinary_overrides: list[ParsedOverride] = []
    for override in overrides:
        if _is_include_target_override(override.path):
            include_overrides.append(override)
            continue
        ordinary_overrides.append(override)
    return tuple(include_overrides), tuple(ordinary_overrides)


def _is_include_target_override(path: str) -> bool:
    return path.split(".")[-1] == "_include_"


def _parse_override(*, raw: str, order: int) -> ParsedOverride:
    if not isinstance(raw, str):
        raise OverrideParseError(f"Override at order {order} must be text: {type(raw).__name__}")

    if "=" not in raw:
        raise OverrideParseError(f"Invalid override at order {order}: {raw!r}")

    path_expression, value_text = raw.split("=", 1)
    path_expression = path_expression.strip()
    if not path_expression:
        raise OverrideParseError(f"Invalid override at order {order}: empty path in {raw!r}")

    operation = "update"
    path = path_expression
    if path_expression.startswith("+"):
        path = path_expression[1:]
        operation = "add"
        if not path:
            raise OverrideParseError(f"Invalid add override at order {order}: empty path in {raw!r}")

    segments = path.split(".")
    if any(not segment for segment in segments):
        raise OverrideParseError(f"Invalid override path at order {order}: {path!r}")

    parsed_value = _parse_override_value(value_text, path=path, order=order)
    return ParsedOverride(
        raw=raw,
        path=path,
        operation=operation,
        value=parsed_value,
        order=order,
    )


def _parse_override_value(value_text: str, *, path: str, order: int) -> PlainData:
    stripped = value_text.strip()

    if stripped == "true":
        return True
    if stripped == "false":
        return False
    if stripped == "null":
        return None

    if re.fullmatch(r"^[+-]?\d+$", stripped):
        try:
            return int(stripped)
        except ValueError as exc:
            raise OverrideParseError(f"Invalid integer value at override path {path} (order={order})") from exc

    if _FLOAT_RE.fullmatch(stripped) is not None:
        try:
            value = float(stripped)
        except ValueError as exc:
            raise OverrideParseError(f"Invalid float value at override path {path} (order={order})") from exc
        if not math.isfinite(value):
            raise OverrideParseError(f"Non-finite float at override path {path} (order={order})")
        return value

    if stripped.startswith('"'):
        try:
            parsed_string = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise OverrideParseError(
                f"Invalid JSON string value at override path {path} (order={order}): {exc.msg}"
            ) from exc
        if not isinstance(parsed_string, str):
            raise OverrideParseError(f"Invalid JSON string value at override path {path} (order={order})")
        return parsed_string

    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise OverrideParseError(f"Invalid JSON value at override path {path} (order={order}): {exc.msg}") from exc
        try:
            parsed_plain = ensure_plain_data(parsed, path=f"override:{path}")
        except PlainDataError as exc:
            raise OverrideParseError(f"Invalid JSON value in override at {path} (order={order})") from exc
        return parsed_plain

    return value_text


def apply_overrides(
    config: Mapping[str, PlainData],
    overrides: Sequence[ParsedOverride],
) -> dict[str, PlainData]:
    """Apply parsed overrides to the resolved mapping."""

    output = ensure_plain_data(config, path="$")
    if not isinstance(output, dict):
        raise OverrideApplyError(
            "Cannot apply overrides to a non-mapping root",
            context=_override_context(
                code="non_mapping_root",
                path="$",
                operation="apply",
                order=-1,
                actual=type(output).__name__,
            ),
        )

    for override in overrides:
        if override.operation == "update":
            _apply_update(output, override)
        else:
            _apply_add(output, override)

    return output


def _apply_update(config: dict[str, PlainData], override: ParsedOverride) -> None:
    parent = _walk_parent(config, override.path, create=False, override=override)
    key = _final_key(override.path)
    if key not in parent:
        raise _override_apply_error(
            f"Missing override target {override.path} (order={override.order})",
            code="missing_override_target",
            override=override,
            details={"missing_key": key},
        )
    parent[key] = override.value


def _apply_add(config: dict[str, PlainData], override: ParsedOverride) -> None:
    parent = _walk_parent(config, override.path, create=True, override=override)
    key = _final_key(override.path)
    if key in parent:
        raise _override_apply_error(
            f"Cannot add existing override target {override.path} (order={override.order})",
            code="existing_override_target",
            override=override,
            details={"existing_key": key},
        )
    parent[key] = override.value


def _walk_parent(
    config: dict[str, PlainData],
    path: str,
    *,
    create: bool,
    override: ParsedOverride,
) -> dict[str, PlainData]:
    parent = config
    segments = path.split(".")

    for segment in segments[:-1]:
        if segment not in parent:
            if not create:
                raise _override_apply_error(
                    f"Missing override path {path} (order={override.order})",
                    code="missing_override_parent",
                    override=override,
                    details={"missing_segment": segment},
                )
            new_child: dict[str, PlainData] = {}
            parent[segment] = new_child
            parent = new_child
            continue

        current = parent[segment]
        if not isinstance(current, dict):
            if create:
                raise _override_apply_error(
                    f"Cannot create parent for override {path}; {segment} is non-mapping at order={override.order}",
                    code="non_mapping_override_parent",
                    override=override,
                    details={"segment": segment, "parent_operation": "create", "actual": type(current).__name__},
                )
            raise _override_apply_error(
                f"Cannot traverse override target {path}; {segment} is non-mapping at order={override.order}",
                code="non_mapping_override_parent",
                override=override,
                details={"segment": segment, "parent_operation": "traverse", "actual": type(current).__name__},
            )

        parent = current

    return parent


def _final_key(path: str) -> str:
    return path.rsplit(".", 1)[-1]


def _override_apply_error(
    message: str,
    *,
    code: str,
    override: ParsedOverride,
    details: dict[str, PlainData],
) -> OverrideApplyError:
    return OverrideApplyError(
        message,
        context=_override_context(
            code=code,
            path=override.path,
            operation=override.operation,
            order=override.order,
            details={
                **details,
                "override_path": override.path,
                "override_operation": override.operation,
                "override_order": override.order,
                "override_raw": _safe_override_raw(override),
                "override_redacted": _override_is_redacted(override),
            },
        ),
    )


def _override_context(
    *,
    code: str,
    path: str,
    operation: str,
    order: int,
    actual: PlainData | None = None,
    details: dict[str, PlainData] | None = None,
) -> ConfigErrorContext:
    return ConfigErrorContext(
        code=code,
        source_kind="ordinary_override",
        source_order=order,
        source_path="<override>",
        config_path=f"$.{path}" if path != "$" else "$",
        actual=actual,
        directive="override",
        remediation=_override_remediation(code, operation),
        details=details,
    )


def _override_remediation(code: str, operation: str) -> str | None:
    if code == "missing_override_target":
        return "Use add override syntax for new keys, or update an existing path."
    if code == "existing_override_target":
        return "Use update override syntax for existing keys."
    if code == "missing_override_parent":
        return "Create the parent mapping first with add override syntax."
    if code == "non_mapping_override_parent":
        return f"Choose a mapping parent path before applying the {operation} override."
    return None


def _safe_override_raw(override: ParsedOverride) -> str:
    return REDACTION_MARKER if _override_is_redacted(override) else override.raw


def _override_is_redacted(override: ParsedOverride) -> bool:
    final_key = override.path.rsplit(".", 1)[-1]
    return contains_secret_like_value(final_key, override.value) or any(
        is_secret_key(segment) for segment in override.path.split(".")
    )
