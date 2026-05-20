"""Config file loading and source capture."""

from __future__ import annotations

import re
from collections.abc import Hashable
from pathlib import Path
from typing import Literal

import yaml

from .digests import hash_bytes
from .plain import PlainData, ensure_plain_data

from .errors import ConfigErrorContext, ConfigLoadError, UnsupportedConfigDirectiveError
from .provenance import ConfigSource

ConfigKind = Literal["base", "overlay"]


class _DuplicateYamlKeyError(Exception):
    """Internal marker for duplicate YAML keys detected by the local loader."""

    def __init__(self, *, key: object, config_path: str) -> None:
        super().__init__(f"Duplicate YAML key at {config_path}: {_display_yaml_key(key)}")
        self.key = key
        self.config_path = config_path


class _StrictConfigLoader(yaml.SafeLoader):
    """Safe YAML loader variant with local duplicate-key rejection."""

    def __init__(self, stream: str) -> None:
        super().__init__(stream)
        self._loom_node_paths: dict[int, str] = {}

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Hashable, object]:  # noqa: FBT001, FBT002
        if not isinstance(node, yaml.MappingNode):
            raise yaml.constructor.ConstructorError(
                None,
                None,
                f"expected a mapping node, but found {node.id}",
                node.start_mark,
            )

        self.flatten_mapping(node)
        mapping: dict[Hashable, object] = {}
        mapping_path = self._loom_node_paths.get(id(node), "$")
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, Hashable):
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found unhashable key",
                    key_node.start_mark,
                )

            child_path = _format_yaml_config_path(mapping_path, key)
            if key in mapping:
                raise _DuplicateYamlKeyError(key=key, config_path=child_path)

            self._loom_node_paths.setdefault(id(value_node), child_path)
            mapping[key] = self.construct_object(value_node, deep=deep)

        return mapping

    def construct_sequence(self, node: yaml.SequenceNode, deep: bool = False) -> list[object]:  # noqa: FBT001, FBT002
        if not isinstance(node, yaml.SequenceNode):
            raise yaml.constructor.ConstructorError(
                None,
                None,
                f"expected a sequence node, but found {node.id}",
                node.start_mark,
            )

        sequence_path = self._loom_node_paths.get(id(node), "$")
        sequence = []
        for index, child_node in enumerate(node.value):
            self._loom_node_paths.setdefault(id(child_node), f"{sequence_path}[{index}]")
            sequence.append(self.construct_object(child_node, deep=deep))
        return sequence


def load_config(path: str | Path, *, kind: ConfigKind, order: int) -> tuple[dict[str, PlainData], ConfigSource]:
    """Load one YAML config source and return the validated plain mapping."""
    plain_mapping, source, _text = _load_config(path=path, kind=kind, order=order)
    return plain_mapping, source


def load_config_with_source_text(path: str | Path, *, kind: ConfigKind, order: int) -> tuple[dict[str, PlainData], ConfigSource, str]:
    """Load one YAML config source and return text for optional snapshot capture."""
    return _load_config(path=path, kind=kind, order=order)


def _load_config(
    path: str | Path,
    *,
    kind: ConfigKind,
    order: int,
) -> tuple[dict[str, PlainData], ConfigSource, str]:
    resolved_path = _resolve_config_path(path, kind=kind, order=order)
    raw = _read_raw_bytes(resolved_path, kind=kind, order=order)
    content_digest = hash_bytes(raw)
    text = _decode_utf8(raw, resolved_path, kind=kind, order=order)
    parsed = _parse_yaml(text, resolved_path, kind=kind, order=order)
    mapping = _validate_root_mapping(parsed, resolved_path, kind=kind, order=order)
    _ensure_no_recursive_aliases(mapping, path="$", active={}, kind=kind, order=order, source_path=resolved_path)
    _ensure_no_unsupported_directives(mapping, path="$", kind=kind, order=order, source_path=resolved_path)
    plain_mapping = _ensure_plain_data(mapping, resolved_path, kind=kind, order=order)

    source = ConfigSource(
        kind=kind,
        path=str(resolved_path),
        order=order,
        content_digest=content_digest,
        size_bytes=len(raw),
    )

    return plain_mapping, source, text


def _resolve_config_path(path: str | Path, *, kind: ConfigKind, order: int) -> Path:
    source = Path(path)
    try:
        path_obj = source.expanduser().resolve(strict=True)
        if not path_obj.is_file():
            raise FileNotFoundError(f"Not a regular file: {path_obj}")
    except OSError as exc:
        raise _config_load_error(
            f"Failed to validate {kind} config path (order={order}) {source}",
            code="invalid_path",
            resolved_path=source,
            kind=kind,
            order=order,
            expected="existing readable YAML file",
            actual=str(type(exc).__name__),
            remediation="Provide a path to an existing config file readable by the current process.",
        ) from exc
    return path_obj


def _read_raw_bytes(path: Path, *, kind: ConfigKind, order: int) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise _config_load_error(
            f"Failed to read {kind} config file (order={order}) at {path}",
            code="read_error",
            resolved_path=path,
            kind=kind,
            order=order,
            expected="readable file bytes",
            actual="unreadable",
            remediation="Ensure the process can read the config file path.",
        ) from exc


def _decode_utf8(data: bytes, path: Path, *, kind: ConfigKind, order: int) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _config_load_error(
            f"Invalid UTF-8 in {kind} config (order={order}) at {path}",
            code="invalid_utf8",
            resolved_path=path,
            kind=kind,
            order=order,
            remediation="Rewrite the file as UTF-8 text.",
        ) from exc


def _parse_yaml(text: str, path: Path, *, kind: ConfigKind, order: int) -> object:
    try:
        documents = tuple(yaml.load_all(text, Loader=_StrictConfigLoader))
    except _DuplicateYamlKeyError as exc:
        key_display = _display_yaml_key(exc.key)
        raise _config_load_error(
            f"Duplicate YAML key in {kind} config (order={order}) at {path}: {key_display}",
            code="duplicate_key",
            resolved_path=path,
            kind=kind,
            order=order,
            config_path=exc.config_path,
            expected="unique YAML mapping keys",
            actual=key_display,
            remediation="Remove the duplicate key or merge the intended values explicitly.",
            details={"key": key_display},
        ) from exc
    except yaml.YAMLError as exc:
        raise _config_load_error(
            f"Failed to parse YAML in {kind} config (order={order}) at {path}",
            code="invalid_yaml",
            resolved_path=path,
            kind=kind,
            order=order,
            remediation="Fix YAML syntax and load again.",
        ) from exc

    if len(documents) == 0:
        raise _config_load_error(
            f"Empty config document in {kind} config (order={order}) at {path}",
            code="empty_root",
            resolved_path=path,
            kind=kind,
            order=order,
            remediation="Provide one non-empty mapping document.",
            actual=0,
            expected=1,
        )
    if len(documents) > 1:
        raise _config_load_error(
            f"Multiple YAML documents in {kind} config (order={order}) at {path}",
            code="multi_document_yaml",
            resolved_path=path,
            kind=kind,
            order=order,
            expected=1,
            actual=len(documents),
            remediation="Use exactly one YAML document per file.",
        )

    return documents[0]


def _display_yaml_key(key: object) -> str:
    if isinstance(key, str):
        return key
    return repr(key)


def _format_yaml_config_path(parent: str, key: object) -> str:
    key_display = _display_yaml_key(key)
    if parent == "$":
        return f"$.{key_display}"
    return f"{parent}.{key_display}"


def _validate_root_mapping(value: object, path: Path, *, kind: ConfigKind, order: int) -> dict[str, PlainData]:
    if not isinstance(value, dict):
        raise _config_load_error(
            f"Invalid {kind} config root in order {order} at {path}; expected mapping, got {type(value).__name__}",
            code="non_mapping_root",
            resolved_path=path,
            kind=kind,
            order=order,
            config_path="$",
            expected="mapping",
            actual=type(value).__name__,
            remediation="Author a YAML mapping at the root of the config.",
        )
    if not value:
        raise _config_load_error(
            f"Empty {kind} config root in order {order} at {path}",
            code="empty_root",
            resolved_path=path,
            kind=kind,
            order=order,
            config_path="$",
            expected="non-empty mapping",
            actual="empty mapping",
            remediation="Provide at least one key in the root config mapping.",
        )
    return value


def _ensure_plain_data(value: object, path: Path, *, kind: ConfigKind, order: int) -> dict[str, PlainData]:
    try:
        plain = ensure_plain_data(value, path="$")
    except Exception as exc:  # noqa: BLE001
        config_path = _extract_config_path(str(exc))
        raise _config_load_error(
            f"Invalid {kind} config data in order {order} at {path}",
            code="non_plain_data",
            resolved_path=path,
            kind=kind,
            order=order,
            config_path=config_path,
            expected="plain YAML value",
            actual=type(value).__name__,
            remediation="Remove non-plain YAML values such as objects, sets, or non-string mapping keys.",
            details={"error": str(exc)},
        ) from exc
    if not isinstance(plain, dict):
        raise _config_load_error(
            f"Invalid {kind} config root in order {order} at {path}; expected mapping, got {type(value).__name__}",
            code="non_mapping_root",
            resolved_path=path,
            kind=kind,
            order=order,
            config_path="$",
            expected="plain mapping",
            actual=type(value).__name__,
            remediation="Author a plain mapping for the config root.",
        )
    return plain


def _ensure_no_recursive_aliases(
    value: object,
    *,
    path: str,
    active: dict[int, str],
    kind: ConfigKind,
    order: int,
    source_path: Path,
) -> None:
    if not isinstance(value, (dict, list)):
        return

    value_id = id(value)
    if value_id in active:
        raise _config_load_error(
            f"Recursive YAML alias in {kind} config (order={order}) at {source_path}",
            code="non_plain_data",
            resolved_path=source_path,
            kind=kind,
            order=order,
            config_path=path,
            expected="acyclic plain YAML value",
            actual="recursive alias",
            remediation="Remove recursive YAML aliases so the config can be represented as plain data.",
            details={"referenced_path": active[value_id]},
        )

    active[value_id] = path
    try:
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}" if path != "$" else f"$.{key}"
                _ensure_no_recursive_aliases(
                    child,
                    path=child_path,
                    active=active,
                    kind=kind,
                    order=order,
                    source_path=source_path,
                )
        else:
            for index, child in enumerate(value):
                child_path = f"{path}[{index}]"
                _ensure_no_recursive_aliases(
                    child,
                    path=child_path,
                    active=active,
                    kind=kind,
                    order=order,
                    source_path=source_path,
                )
    finally:
        del active[value_id]


def _ensure_no_unsupported_directives(
    value: object,
    *,
    path: str,
    kind: ConfigKind,
    order: int,
    source_path: Path,
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path != "$" else f"$.{key}"
            if key in {"_copy_", "_schema_"}:
                directive = key
                expected = (
                    "v1-supported authored directives"
                    if key == "_copy_"
                    else "schema declarations from authored files"
                )
                remediation = (
                    "Use explicit overlays or include/replace behavior instead; _copy_ is deferred."
                    if key == "_copy_"
                    else (
                        "Remove `_schema_` from authored config files. "
                        "Phase 10 composition treats schema authorship directives as unsupported."
                    )
                )
                raise UnsupportedConfigDirectiveError(
                    f"Unsupported {directive} directive in {kind} config (order={order}) at {source_path}",
                    context=_build_context(
                        code="unsupported_directive",
                        kind=kind,
                        order=order,
                        source_path=source_path,
                        config_path=child_path,
                        directive=directive,
                        expected=expected,
                        actual=directive,
                        remediation=remediation,
                    ),
                )
            _ensure_no_unsupported_directives(
                child,
                path=child_path,
                kind=kind,
                order=order,
                source_path=source_path,
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            _ensure_no_unsupported_directives(
                child,
                path=child_path,
                kind=kind,
                order=order,
                source_path=source_path,
            )


def _extract_config_path(message: str) -> str:
    match = re.search(r" at (.+?):", message)
    if match is None:
        return "$"
    return match.group(1)


def _build_context(
    *,
    code: str,
    kind: ConfigKind,
    order: int,
    source_path: Path,
    config_path: str | None = None,
    expected: object | None = None,
    actual: object | None = None,
    directive: str | None = None,
    remediation: str | None = None,
    details: object | None = None,
) -> ConfigErrorContext:
    plain_details = ensure_plain_data(details) if details is not None else None
    if plain_details is not None and not isinstance(plain_details, dict):
        raise TypeError("Config error context details must be a mapping")

    return ConfigErrorContext(
        code=code,
        source_kind=kind,
        source_order=order,
        source_path=str(source_path),
        config_path=config_path,
        expected=ensure_plain_data(expected) if expected is not None else None,
        actual=ensure_plain_data(actual) if actual is not None else None,
        directive=directive,
        remediation=remediation,
        details=plain_details,
    )


def _config_load_error(
    message: str,
    *,
    code: str,
    resolved_path: Path,
    kind: ConfigKind,
    order: int,
    config_path: str | None = None,
    expected: object | None = None,
    actual: object | None = None,
    directive: str | None = None,
    remediation: str | None = None,
    details: object | None = None,
) -> ConfigLoadError:
    context = _build_context(
        code=code,
        kind=kind,
        order=order,
        source_path=resolved_path,
        config_path=config_path,
        expected=expected,
        actual=actual,
        directive=directive,
        remediation=remediation,
        details=details,
    )

    return ConfigLoadError(message, context=context)
