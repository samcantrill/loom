"""Interpolation wrapper around OmegaConf."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping, Sequence
from typing import Any, cast

from omegaconf import OmegaConf
from omegaconf.errors import OmegaConfBaseException

from loom.serialization import PlainData, ensure_plain_data
from loom.serialization import to_plain_data

from .errors import ConfigErrorContext, ConfigInterpolationError, ConfigUnsupportedResolverError
from .source_maps import ConfigPath, format_config_path

_ALLOWED_RUNTIME_RESOLVERS = frozenset({"oc.env"})


@dataclass(frozen=True, slots=True)
class ResolverExpressionRecord:
    config_path: str
    token: str
    resolver: str
    expression: str


def resolve_interpolation(
    mapping: Mapping[str, Any],
    *,
    path: str = "$",
    source_kind: str = "runtime",
    source_order: int = 0,
    source_path: str = "$",
) -> dict[str, PlainData]:
    plain_config, resolver_records = scan_resolver_expressions(mapping, path=path)
    _reject_unsupported_resolvers(
        resolver_records,
        source_kind=source_kind,
        source_order=source_order,
        source_path=source_path,
    )
    try:
        config = OmegaConf.create(dict(plain_config))
    except OmegaConfBaseException as exc:
        raise ConfigInterpolationError(f"Failed to prepare interpolation context at {path}") from exc

    try:
        resolved = OmegaConf.to_container(config, resolve=True)
    except OmegaConfBaseException as exc:
        raise ConfigInterpolationError(f"Failed to resolve interpolation at {path}") from exc

    try:
        plain = ensure_plain_data(resolved, path=path)
    except Exception as exc:  # noqa: BLE001
        raise ConfigInterpolationError(f"Interpolation produced non-plain values at {path}") from exc
    if not isinstance(plain, dict):
        raise ConfigInterpolationError(f"Interpolation produced non-mapping root at {path}")
    return plain


def scan_resolver_expressions(
    mapping: Mapping[str, Any],
    *,
    path: str = "$",
) -> tuple[dict[str, PlainData], tuple[ResolverExpressionRecord, ...]]:
    plain_config = to_plain_data(mapping, path=path)
    if not isinstance(plain_config, dict):
        raise ConfigInterpolationError(f"Interpolation scan input must be a mapping at {path}")
    records: list[ResolverExpressionRecord] = []
    _collect_resolver_records(plain_config, root_path=path, config_path=(), records=records)
    return plain_config, tuple(records)


def _reject_unsupported_resolvers(
    records: Sequence[ResolverExpressionRecord],
    *,
    source_kind: str,
    source_order: int,
    source_path: str,
) -> None:
    unsupported = [record for record in records if record.resolver not in _ALLOWED_RUNTIME_RESOLVERS]
    if not unsupported:
        return

    first = unsupported[0]
    raise ConfigUnsupportedResolverError(
        f"Unsupported resolver {first.resolver!r} at {first.config_path} in Phase 8; only 'oc.env' is allowed.",
        context=ConfigErrorContext(
            code="unsupported_resolver",
            source_kind=source_kind,
            source_order=source_order,
            source_path=source_path,
            config_path=first.config_path,
            directive="interpolation",
            expected="oc.env",
            actual=first.resolver,
            remediation=(
                "Phase 8 only allows oc.env resolver execution during runtime resolution. "
                "Register and execute custom resolvers are intentionally rejected."
            ),
            details=cast(dict[str, PlainData], {
                "authored_expression": first.expression,
                "interpolation_token": first.token,
                "unsupported_resolver": first.resolver,
                "supported_resolvers": sorted(_ALLOWED_RUNTIME_RESOLVERS),
                "resolver_expression_count": len(records),
                "unsupported_resolver_count": len(unsupported),
            }),
        ),
    )


def _collect_resolver_records(
    value: Any,
    *,
    root_path: str,
    config_path: ConfigPath,
    records: list[ResolverExpressionRecord],
) -> None:
    if isinstance(value, str):
        for token, expression in _iter_interpolation_tokens(value):
            resolver = _extract_resolver_name(expression)
            if resolver is None:
                continue
            records.append(
                ResolverExpressionRecord(
                    config_path=_format_scan_path(root_path, config_path),
                    token=token,
                    resolver=resolver,
                    expression=expression,
                )
            )
        return

    if isinstance(value, Mapping):
        for key, child in value.items():
            _collect_resolver_records(
                child,
                root_path=root_path,
                config_path=config_path + (key,),
                records=records,
            )
        return

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _collect_resolver_records(
                child,
                root_path=root_path,
                config_path=config_path + (index,),
                records=records,
            )


def _iter_interpolation_tokens(value: str) -> tuple[tuple[str, str], ...]:
    tokens: list[tuple[str, str]] = []
    index = 0
    while True:
        start = value.find("${", index)
        if start < 0:
            return tuple(tokens)

        depth = 1
        cursor = start + 2
        while cursor < len(value) and depth > 0:
            if value.startswith("${", cursor):
                depth += 1
                cursor += 2
                continue
            if value[cursor] == "}":
                depth -= 1
            cursor += 1

        if depth != 0:
            index = start + 2
            continue

        token = value[start:cursor]
        expression = token[2:-1]
        tokens.append((token, expression))
        tokens.extend(_iter_interpolation_tokens(expression))
        index = cursor


def _format_scan_path(root_path: str, config_path: ConfigPath) -> str:
    if root_path == "$":
        return format_config_path(config_path)
    return f"{root_path}{format_config_path(config_path)[1:]}"


def _extract_resolver_name(value: str) -> str | None:
    token = value.strip()
    if ":" not in token:
        return None
    return token.split(":", 1)[0].strip()
