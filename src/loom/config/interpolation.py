"""Interpolation wrapper around OmegaConf."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from omegaconf import OmegaConf
from omegaconf.errors import OmegaConfBaseException
from omegaconf.grammar_parser import parse as parse_omegaconf_interpolation
from omegaconf.grammar_visitor import GrammarVisitor

from loom.serialization import PlainData, ensure_plain_data
from loom.serialization import to_plain_data

from .errors import ConfigErrorContext, ConfigInterpolationError, ConfigUnsupportedResolverError
from .redaction import REDACTION_MARKER, is_secret_path
from .source_maps import ConfigPath, ValueAuthorship, format_config_path

_ALLOWED_RUNTIME_RESOLVERS = frozenset({"oc.env"})
_ENV_DEFAULT_MISSING = object()
_INTERPOLATION_OPEN_PATTERN: re.Pattern[str] = re.compile(r"(\\*)\$\{")


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
    value_authorship: Mapping[str, ValueAuthorship] | None = None,
) -> dict[str, PlainData]:
    plain_config, resolver_records = scan_resolver_expressions(mapping, path=path)
    _reject_unsupported_resolvers(
        resolver_records,
        source_kind=source_kind,
        source_order=source_order,
        source_path=source_path,
        value_authorship=value_authorship or {},
    )
    try:
        runtime_config = _resolve_allowed_runtime_resolvers(
            plain_config,
            root_path=path,
            resolver_records=resolver_records,
        )
        config = OmegaConf.create(dict(runtime_config))
    except OmegaConfBaseException as exc:
        raise ConfigInterpolationError(f"Failed to prepare interpolation context at {path}") from exc

    try:
        resolved = OmegaConf.to_container(config, resolve=True)
    except OmegaConfBaseException as exc:
        raise ConfigInterpolationError(
            f"Failed to resolve interpolation at {path}",
            context=_interpolation_context(
                code="interpolation_resolution_failed",
                config_path=path,
                source_kind=source_kind,
                source_order=source_order,
                source_path=source_path,
                value_authorship=value_authorship or {},
                details={"reason": type(exc).__name__},
            ),
        ) from exc

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
    value_authorship: Mapping[str, ValueAuthorship],
) -> None:
    unsupported = [record for record in records if record.resolver not in _ALLOWED_RUNTIME_RESOLVERS]
    if not unsupported:
        return

    first = unsupported[0]
    raise ConfigUnsupportedResolverError(
        f"Unsupported resolver {first.resolver!r} at {first.config_path}; only 'oc.env' is allowed.",
        context=ConfigErrorContext(
            code="unsupported_resolver",
            source_kind=_authored_source_kind(first.config_path, source_kind, value_authorship),
            source_order=_authored_source_order(first.config_path, source_order, value_authorship),
            source_path=_authored_source_path(first.config_path, source_path, value_authorship),
            config_path=first.config_path,
            directive="interpolation",
            expected="oc.env",
            actual=first.resolver,
            remediation=(
                "Use oc.env for runtime environment values, or replace this resolver expression with a plain "
                "authored value before composition."
            ),
            details=cast(
                dict[str, PlainData],
                {
                    "authored_expression": _safe_authored_expression(first.config_path, first.expression),
                    "interpolation_token": _safe_authored_expression(first.config_path, first.token),
                    "unsupported_resolver": first.resolver,
                    "supported_resolvers": sorted(_ALLOWED_RUNTIME_RESOLVERS),
                    "resolver_expression_count": len(records),
                    "unsupported_resolver_count": len(unsupported),
                    **_authorship_details(first.config_path, value_authorship),
                },
            ),
        ),
    )


def _safe_authored_expression(config_path: str, expression: str) -> str:
    return REDACTION_MARKER if is_secret_path(config_path) else expression


def _interpolation_context(
    *,
    code: str,
    config_path: str,
    source_kind: str,
    source_order: int,
    source_path: str,
    value_authorship: Mapping[str, ValueAuthorship],
    details: dict[str, PlainData],
) -> ConfigErrorContext:
    return ConfigErrorContext(
        code=code,
        source_kind=_authored_source_kind(config_path, source_kind, value_authorship),
        source_order=_authored_source_order(config_path, source_order, value_authorship),
        source_path=_authored_source_path(config_path, source_path, value_authorship),
        config_path=config_path,
        directive="interpolation",
        remediation="Check that the referenced config path exists after include, recipe, and override composition.",
        details=cast(dict[str, PlainData], {**details, **_authorship_details(config_path, value_authorship)}),
    )


def _authored_source_kind(
    config_path: str,
    fallback: str,
    value_authorship: Mapping[str, ValueAuthorship],
) -> str:
    record = value_authorship.get(config_path)
    return record.source_kind if record is not None else fallback


def _authored_source_order(
    config_path: str,
    fallback: int,
    value_authorship: Mapping[str, ValueAuthorship],
) -> int:
    record = value_authorship.get(config_path)
    return record.source_order if record is not None else fallback


def _authored_source_path(
    config_path: str,
    fallback: str,
    value_authorship: Mapping[str, ValueAuthorship],
) -> str:
    record = value_authorship.get(config_path)
    return record.source_path if record is not None else fallback


def _authorship_details(
    config_path: str,
    value_authorship: Mapping[str, ValueAuthorship],
) -> dict[str, PlainData]:
    record = value_authorship.get(config_path)
    if record is None:
        return {"authorship_missing": True}
    return {
        "authorship_missing": False,
        "authorship": record.to_dict(),
    }


def _resolve_allowed_runtime_resolvers(
    mapping: Mapping[str, PlainData],
    *,
    root_path: str,
    resolver_records: Sequence[ResolverExpressionRecord],
) -> dict[str, PlainData]:
    resolver_paths = frozenset(
        record.config_path for record in resolver_records if record.resolver in _ALLOWED_RUNTIME_RESOLVERS
    )
    if not resolver_paths:
        return dict(mapping)

    resolved = _resolve_runtime_resolver_values(
        cast(PlainData, dict(mapping)),
        root_path=root_path,
        config_path=(),
        resolver_paths=resolver_paths,
    )
    if not isinstance(resolved, dict):
        raise ConfigInterpolationError(f"Runtime resolver preparation produced non-mapping root at {root_path}")
    return resolved


def _resolve_runtime_resolver_values(
    value: PlainData,
    *,
    root_path: str,
    config_path: ConfigPath,
    resolver_paths: frozenset[str],
) -> PlainData:
    if isinstance(value, str):
        if _format_scan_path(root_path, config_path) not in resolver_paths:
            return value
        return _resolve_runtime_string(value, path=_format_scan_path(root_path, config_path))

    if isinstance(value, dict):
        return {
            key: _resolve_runtime_resolver_values(
                child,
                root_path=root_path,
                config_path=config_path + (key,),
                resolver_paths=resolver_paths,
            )
            for key, child in value.items()
        }

    if isinstance(value, list):
        return [
            _resolve_runtime_resolver_values(
                child,
                root_path=root_path,
                config_path=config_path + (index,),
                resolver_paths=resolver_paths,
            )
            for index, child in enumerate(value)
        ]

    return value


def _resolve_runtime_string(value: str, *, path: str) -> PlainData:
    visitor = GrammarVisitor(
        node_interpolation_callback=cast(Any, _preserve_node_interpolation),
        resolver_interpolation_callback=_resolve_runtime_resolver,
        memo=set(),
    )
    try:
        resolved = visitor.visit(parse_omegaconf_interpolation(value))
    except ConfigInterpolationError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ConfigInterpolationError(f"Failed to resolve runtime resolver at {path}") from exc

    try:
        return ensure_plain_data(resolved, path=path)
    except Exception as exc:  # noqa: BLE001
        raise ConfigInterpolationError(f"Runtime resolver produced non-plain value at {path}") from exc


def _preserve_node_interpolation(inter_key: str, memo: set[int] | None = None) -> str:
    _ = memo
    return f"${{{inter_key}}}"


def _resolve_runtime_resolver(
    *,
    name: str,
    args: tuple[Any, ...],
    args_str: tuple[str, ...],
) -> str | None:
    _ = args_str
    if name != "oc.env":
        raise ConfigInterpolationError(f"Unsupported runtime resolver {name!r}")

    value = _loom_oc_env(*args)
    if isinstance(value, str):
        return _escape_interpolation_openings(value)
    return value


def _loom_oc_env(key: object, default: object = _ENV_DEFAULT_MISSING) -> str | None:
    if not isinstance(key, str):
        raise TypeError(f"str expected, not {type(key).__name__}")
    try:
        return os.environ[key]
    except KeyError:
        if default is not _ENV_DEFAULT_MISSING:
            return str(default) if default is not None else None
        raise KeyError(f"Environment variable '{key}' not found")


def _escape_interpolation_openings(value: str) -> str:
    return _INTERPOLATION_OPEN_PATTERN.sub(_escape_interpolation_opening_match, value)


def _escape_interpolation_opening_match(match: re.Match[str]) -> str:
    slashes = match.group(1)
    return ("\\" * (len(slashes) * 2 + 1)) + "${"


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
