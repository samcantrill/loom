"""Helpers for URI parsing and normalization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from .errors import UnsupportedURIError


@dataclass(frozen=True, slots=True)
class ParsedURI:
    """Parsed URI decomposition for local and remote inputs."""

    raw: str
    scheme: str | None
    path: str
    authority: str | None = None
    query: str | None = None
    fragment: str | None = None


def parse_uri(uri: str | Path) -> ParsedURI:
    """Parse local paths and URI strings without touching the filesystem."""

    raw = _normalize_uri_input(uri)
    parsed = urlsplit(raw)

    if parsed.scheme:
        scheme = parsed.scheme.lower()
        if scheme == "file":
            authority = _normalize_file_authority(parsed.netloc)
            return ParsedURI(
                raw=raw,
                scheme=scheme,
                path=unquote(parsed.path),
                authority=authority,
                query=_none_if_empty(parsed.query),
                fragment=_none_if_empty(parsed.fragment),
            )
        return ParsedURI(
            raw=raw,
            scheme=scheme,
            path=parsed.path,
            authority=parsed.netloc or None,
            query=_none_if_empty(parsed.query),
            fragment=_none_if_empty(parsed.fragment),
        )

    return ParsedURI(
        raw=raw,
        scheme=None,
        path=raw,
        authority=None,
        query=None,
        fragment=None,
    )


def get_uri_scheme(uri: str | Path) -> str | None:
    """Return the lowercased scheme when one is explicitly present."""

    return parse_uri(uri).scheme


def is_file_uri(uri: str | Path) -> bool:
    """Return ``True`` when the input is an explicit local file URI."""

    return get_uri_scheme(uri) == "file"


def uri_to_path(uri: str | Path) -> Path:
    """Resolve local file-like inputs into a local path."""

    parsed = parse_uri(uri)

    if parsed.scheme is None:
        return Path(parsed.path)

    if parsed.scheme == "file":
        _require_local_file_uri(parsed)
        return Path(parsed.path)

    raise UnsupportedURIError(f"Unsupported URI scheme for local path conversion: {parsed.scheme!r}")


def path_to_file_uri(path: str | Path) -> str:
    """Create a quoted ``file://`` URI from an absolute local path."""

    path_obj = Path(path)
    if not path_obj.is_absolute():
        raise UnsupportedURIError(f"Cannot convert non-absolute path to file URI: {path!r}")

    quoted = quote(path_obj.as_posix(), safe="/")
    return f"file://{quoted}"


def normalize_uri(uri: str | Path, *, base_dir: str | Path | None = None) -> str:
    """Normalize local paths and URIs to standard I/O representations."""

    parsed = parse_uri(uri)

    if parsed.scheme == "file":
        return path_to_file_uri(uri_to_path(parsed.raw))

    if parsed.scheme is None:
        path = Path(parsed.path)
        if path.is_absolute():
            return path_to_file_uri(path)
        if base_dir is None:
            return path.as_posix()
        root = Path(base_dir).resolve(strict=False)
        return path_to_file_uri((root / path).resolve(strict=False))

    return parsed.raw


def _normalize_uri_input(uri: str | Path) -> str:
    if isinstance(uri, Path):
        raw = str(uri)
    else:
        raw = uri
    if not isinstance(raw, str):
        raise UnsupportedURIError(f"Unsupported URI/path type: {type(uri)!r}")
    if not raw or raw.strip() != raw:
        raise UnsupportedURIError(f"Unsupported URI/path with empty or whitespace value: {uri!r}")
    return raw


def _normalize_file_authority(authority: str) -> str | None:
    if not authority or authority.lower() == "localhost":
        return None
    return authority


def _none_if_empty(value: str) -> str | None:
    return value or None


def _require_local_file_uri(parsed: ParsedURI) -> None:
    if parsed.query is not None or parsed.fragment is not None:
        raise UnsupportedURIError(f"Remote-style file URI cannot be converted to path: {parsed.raw!r}")
    if parsed.authority is not None:
        raise UnsupportedURIError(f"Non-local file authority {parsed.authority!r} for URI {parsed.raw!r}")


__all__ = [
    "ParsedURI",
    "parse_uri",
    "get_uri_scheme",
    "is_file_uri",
    "uri_to_path",
    "path_to_file_uri",
    "normalize_uri",
]
