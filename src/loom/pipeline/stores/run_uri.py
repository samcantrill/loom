"""Run URI parsing and local path resolution for run stores."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from loom.io.uris import path_to_file_uri
from loom.timestamps import safe_timestamp_for_path

from .errors import InvalidRunURIError, RunAlreadyExistsError


@dataclass(frozen=True, slots=True)
class LocalRunURI:
    """Resolved local run URI and filesystem path."""

    uri: str
    path: Path


def validate_run_uri(
    value: object, *, cwd: str | Path | None = None, field: str = "run_uri"
) -> str:
    """Validate and resolve a v2 local run URI to absolute ``file:///`` form."""

    return resolve_local_run_uri(value, cwd=cwd, field=field).uri


def run_uri_to_path(
    value: object, *, cwd: str | Path | None = None, field: str = "run_uri"
) -> Path:
    """Validate a v2 local run URI and return its resolved local path."""

    return resolve_local_run_uri(value, cwd=cwd, field=field).path


def path_to_run_uri(path: str | Path) -> str:
    """Return the absolute ``file:///`` URI for a local run path."""

    return path_to_file_uri(Path(path).resolve(strict=False))


def resolve_local_run_uri(
    value: object, *, cwd: str | Path | None = None, field: str = "run_uri"
) -> LocalRunURI:
    """Validate strict v2 local run URI syntax and resolve to an absolute URI."""

    raw = _raw_uri(value, field=field)
    if "?" in raw or "#" in raw:
        raise InvalidRunURIError(f"{field} must not include query strings or fragments")

    path: Path
    if raw.startswith("file://./") or raw.startswith("file://../"):
        relative = unquote(raw[len("file://") :])
        root = Path.cwd() if cwd is None else Path(cwd)
        path = (root / relative).resolve(strict=False)
    else:
        parsed = urlsplit(raw)
        if parsed.scheme.lower() != "file":
            raise InvalidRunURIError(f"{field} must use explicit local file:// syntax")
        if parsed.netloc:
            raise InvalidRunURIError(
                f"{field} must not include a file URI authority: {parsed.netloc!r}"
            )
        if parsed.query or parsed.fragment:
            raise InvalidRunURIError(
                f"{field} must not include query strings or fragments"
            )
        decoded_path = unquote(parsed.path)
        if not decoded_path or not decoded_path.startswith("/"):
            raise InvalidRunURIError(
                f"{field} must be file:///absolute/path, file://./path, or file://../path"
            )
        path = Path(decoded_path).resolve(strict=False)

    if path == Path(path.anchor):
        raise InvalidRunURIError(f"{field} must identify a run directory, not a root")
    return LocalRunURI(uri=path_to_file_uri(path), path=path)


def allocate_local_run_uri(root: str | Path, *, max_attempts: int = 1000) -> str:
    """Allocate a collision-free local run URI under ``root`` without writing it."""

    if isinstance(max_attempts, bool) or max_attempts <= 0:
        raise InvalidRunURIError("max_attempts must be a positive integer")
    root_path = Path(root).resolve(strict=False)
    base_name = safe_timestamp_for_path(timespec="seconds")
    for index in range(max_attempts):
        suffix = "" if index == 0 else f"-{index + 1}"
        candidate = root_path / f"{base_name}{suffix}"
        if not candidate.exists():
            return path_to_file_uri(candidate)
    raise RunAlreadyExistsError(
        f"could not allocate a run URI under {root_path} after {max_attempts} attempts"
    )


def _raw_uri(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise InvalidRunURIError(f"{field} must be a non-empty string")
    if not value or value.strip() != value:
        raise InvalidRunURIError(
            f"{field} must be a non-empty string without surrounding whitespace"
        )
    if "\x00" in value:
        raise InvalidRunURIError(f"{field} must not contain NUL characters")
    if not value.startswith("file://"):
        raise InvalidRunURIError(f"{field} must use explicit local file:// syntax")
    return value


__all__ = [
    "LocalRunURI",
    "allocate_local_run_uri",
    "path_to_run_uri",
    "resolve_local_run_uri",
    "run_uri_to_path",
    "validate_run_uri",
]
