"""Internal path and name validation helpers for store backends."""

from __future__ import annotations

from pathlib import Path

from .errors import UnsafeStorePathError


_RUN_RESERVED_NAMES = frozenset({".", ".."})


VALID_CONFIG_SNAPSHOTS = {
    "raw": "raw.yaml",
    "overlays": "overlays.yaml",
    "cli_overrides": "cli_overrides.yaml",
    "resolved": "resolved.yaml",
    "resolved_redacted": "resolved.redacted.yaml",
}

VALID_PROVENANCE_NAMES = {
    "environment": "environment.json",
    "git": "git.json",
    "command": "command.json",
    "dependencies": "dependencies.json",
}

VALID_LOG_STREAMS = frozenset({"stdout", "stderr"})


def validate_stage_name(value: object, *, field: str = "stage_name") -> str:
    """Validate a stage name for storage paths and artifact keys."""

    return _validate_identifier(value, field=field, allow_dot=False)


def validate_output_name(value: object, *, field: str = "name") -> str:
    """Validate an artifact output name for storage paths and index keys."""

    return _validate_identifier(value, field=field, allow_dot=False)


def validate_temp_component(value: object, *, field: str = "path") -> str:
    """Validate internal temporary path components used for atomic writes."""

    return _validate_identifier(value, field=field, allow_dot=True)


def validate_config_snapshot_name(value: object) -> str:
    value_text = _validate_identifier(value, field="config_name", allow_dot=True)
    if value_text not in VALID_CONFIG_SNAPSHOTS:
        valid = ", ".join(sorted(VALID_CONFIG_SNAPSHOTS))
        raise UnsafeStorePathError(
            f"Unsupported config snapshot name {value_text!r}; expected one of: {valid}",
        )
    return value_text


def validate_provenance_name(value: object) -> str:
    value_text = _validate_identifier(value, field="provenance_name", allow_dot=True)
    if value_text not in VALID_PROVENANCE_NAMES:
        valid = ", ".join(sorted(VALID_PROVENANCE_NAMES))
        raise UnsafeStorePathError(
            f"Unsupported provenance document name {value_text!r}; expected one of: {valid}",
        )
    return value_text


def validate_log_stream(value: object) -> str:
    value_text = _validate_identifier(value, field="log_stream", allow_dot=True)
    if value_text not in VALID_LOG_STREAMS:
        valid = ", ".join(sorted(VALID_LOG_STREAMS))
        raise UnsafeStorePathError(
            f"Unsupported log stream {value_text!r}; expected one of: {valid}",
        )
    return value_text


def resolve_path_or_raise(path: str | Path, *, field: str = "path") -> Path:
    """Resolve a path to an absolute path for containment checks."""

    if not isinstance(path, (str, Path)):
        raise UnsafeStorePathError(f"{field} must be a string path: {path!r}")
    return Path(path).resolve(strict=False)


def ensure_subpath(path: Path, root: Path, *, field: str = "path") -> Path:
    """Validate ``path`` is within ``root`` after normalization."""

    resolved_path = path.resolve(strict=False)
    resolved_root = root.resolve(strict=False)
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise UnsafeStorePathError(
            f"{field} must stay inside {resolved_root}; got {resolved_path}",
        ) from exc
    return resolved_path


def _validate_identifier(value: object, *, field: str, allow_dot: bool) -> str:
    if not isinstance(value, str):
        raise UnsafeStorePathError(f"{field} must be a non-empty string")
    if not value:
        raise UnsafeStorePathError(f"{field} must be a non-empty string")
    if value.strip() != value:
        raise UnsafeStorePathError(
            f"{field} must not contain leading or trailing whitespace: {value!r}"
        )
    if value in _RUN_RESERVED_NAMES:
        raise UnsafeStorePathError(f"{field} cannot be '.' or '..': {value!r}")
    if "/" in value or "\\" in value:
        raise UnsafeStorePathError(f"{field} cannot contain path separators: {value!r}")
    if "\x00" in value:
        raise UnsafeStorePathError(f"{field} cannot contain NUL characters: {value!r}")
    if any(ch.isspace() or ord(ch) < 32 for ch in value):
        raise UnsafeStorePathError(
            f"{field} cannot contain whitespace or control characters: {value!r}"
        )
    if (not allow_dot) and "." in value:
        raise UnsafeStorePathError(f"{field} cannot contain '.': {value!r}")
    return value
