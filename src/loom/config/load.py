"""Config file loading and source capture."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml

from loom.fingerprints import hash_bytes
from loom.serialization import PlainData, ensure_plain_data

from .errors import ConfigLoadError
from .provenance import ConfigSource

ConfigKind = Literal["base", "overlay"]


def load_config(path: str | Path, *, kind: ConfigKind, order: int) -> tuple[dict[str, PlainData], ConfigSource]:
    """Load one YAML config source and return the validated plain mapping."""

    resolved_path = _resolve_config_path(path, kind=kind, order=order)
    raw = _read_raw_bytes(resolved_path, kind=kind, order=order)
    content_digest = hash_bytes(raw)
    text = _decode_utf8(raw, resolved_path, kind=kind, order=order)
    parsed = _parse_yaml(text, resolved_path, kind=kind, order=order)
    mapping = _validate_root_mapping(parsed, resolved_path, kind=kind, order=order)

    source = ConfigSource(
        kind=kind,
        path=str(resolved_path),
        order=order,
        content_digest=content_digest,
        size_bytes=len(raw),
    )
    return mapping, source


def _resolve_config_path(path: str | Path, *, kind: ConfigKind, order: int) -> Path:
    source = Path(path)
    try:
        path_obj = source.expanduser().resolve(strict=True)
        if not path_obj.is_file():
            raise FileNotFoundError(f"Not a regular file: {path_obj}")
    except OSError as exc:
        raise ConfigLoadError(f"Failed to validate {kind} config path (order={order}) {source}") from exc
    return path_obj


def _read_raw_bytes(path: Path, *, kind: ConfigKind, order: int) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ConfigLoadError(f"Failed to read {kind} config file (order={order}) at {path}") from exc


def _decode_utf8(data: bytes, path: Path, *, kind: ConfigKind, order: int) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigLoadError(f"Invalid UTF-8 in {kind} config (order={order}) at {path}") from exc


def _parse_yaml(text: str, path: Path, *, kind: ConfigKind, order: int) -> object:
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigLoadError(f"Failed to parse YAML in {kind} config (order={order}) at {path}") from exc

    if parsed is None:
        raise ConfigLoadError(f"Empty config document in {kind} config (order={order}) at {path}")
    return parsed


def _validate_root_mapping(value: object, path: Path, *, kind: ConfigKind, order: int) -> dict[str, PlainData]:
    if not isinstance(value, dict):
        raise ConfigLoadError(
            f"Invalid {kind} config root in order {order} at {path}; expected mapping, got {type(value).__name__}"
        )

    try:
        plain = ensure_plain_data(value, path=f"{path}")
    except Exception as exc:  # noqa: BLE001
        raise ConfigLoadError(f"Invalid {kind} config data in order {order} at {path}") from exc
    if not isinstance(plain, dict):
        raise ConfigLoadError(
            f"Invalid {kind} config root in order {order} at {path}; expected mapping, got {type(value).__name__}"
        )
    return plain
