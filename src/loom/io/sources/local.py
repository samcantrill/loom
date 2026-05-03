"""Local filesystem data source implementation."""

from __future__ import annotations

from dataclasses import dataclass
from glob import glob as _glob
from pathlib import Path
from typing import BinaryIO, Mapping, TextIO
from datetime import datetime, timezone

from loom.serialization import PlainData
from loom.timestamps import utc_timestamp

from loom.io.uris import is_file_uri, parse_uri, path_to_file_uri, uri_to_path
from .errors import DataSourceError, SourceNotFoundError, SourcePermissionError, UnsupportedSourceOperationError

_ALLOWED_MODES = frozenset({"rb", "wb", "rt", "wt"})


@dataclass(frozen=True, slots=True)
class LocalFileSystemSource:
    """Filesystem-backed source for local paths and local file URIs."""

    root: Path | None = None
    name: str = "local"

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("LocalFileSystemSource name must be a non-empty string")
        if self.root is not None:
            object.__setattr__(self, "root", Path(self.root).resolve(strict=False))

    def supports(self, uri: str | Path) -> bool:
        try:
            parsed = parse_uri(uri)
        except Exception:
            return False
        if parsed.scheme is None:
            return bool(parsed.path)
        if not is_file_uri(uri):
            return False
        if parsed.query is not None or parsed.fragment is not None:
            return False
        return parsed.authority is None

    def resolve(self, uri: str | Path) -> Path:
        if not self.supports(uri):
            raise UnsupportedSourceOperationError(f"{self.name} source does not support URI {uri!r}")

        try:
            parsed = parse_uri(uri)
            path = uri_to_path(uri) if parsed.scheme == "file" else Path(parsed.path)
            return self._resolve_local_path(path)
        except UnsupportedSourceOperationError:
            raise
        except Exception as exc:
            raise UnsupportedSourceOperationError(f"{self.name} source failed to resolve {uri!r}") from exc

    def open(self, uri: str | Path, mode: str = "rb", *, encoding: str = "utf-8") -> BinaryIO | TextIO:
        if not self.supports(uri):
            raise UnsupportedSourceOperationError(f"{self.name} source does not support URI {uri!r}")
        if not isinstance(mode, str):
            raise UnsupportedSourceOperationError(f"{self.name} source received invalid mode {mode!r}")
        if mode not in _ALLOWED_MODES:
            raise UnsupportedSourceOperationError(f"{self.name} source does not support mode {mode!r}")

        path = self.resolve(uri)
        try:
            if "b" in mode:
                return open(path, mode)
            return open(path, mode, encoding=encoding)
        except FileNotFoundError as exc:
            raise SourceNotFoundError(f"{self.name} source cannot open missing resource: {path}") from exc
        except PermissionError as exc:
            raise SourcePermissionError(f"{self.name} source permission denied opening {path}") from exc
        except OSError as exc:
            raise DataSourceError(f"{self.name} source open failure for {path} (mode={mode!r})") from exc

    def exists(self, uri: str | Path) -> bool:
        if not self.supports(uri):
            return False
        try:
            return self.resolve(uri).exists()
        except UnsupportedSourceOperationError:
            return False

    def stat(self, uri: str | Path) -> Mapping[str, PlainData]:
        if not self.supports(uri):
            raise UnsupportedSourceOperationError(f"{self.name} source does not support URI {uri!r}")
        path = self.resolve(uri)
        if not path.exists():
            raise SourceNotFoundError(f"{self.name} source stat missing path: {path}")

        try:
            data = path.stat()
        except PermissionError as exc:
            raise SourcePermissionError(f"{self.name} source lacks permissions for {path}") from exc
        except OSError as exc:
            raise DataSourceError(f"{self.name} source could not stat {path}") from exc

        return {
            "uri": path_to_file_uri(path),
            "backend": self.name,
            "exists": True,
            "size_bytes": data.st_size,
            "mtime": utc_timestamp(datetime.fromtimestamp(data.st_mtime, tz=timezone.utc), timespec="seconds"),
        }

    def glob(self, pattern: str | Path) -> tuple[str, ...]:
        if not self.supports(pattern):
            raise UnsupportedSourceOperationError(f"{self.name} source does not support pattern {pattern!r}")

        parsed = parse_uri(pattern)
        search_pattern = uri_to_path(pattern).as_posix() if is_file_uri(pattern) else parsed.path
        if Path(search_pattern).is_absolute():
            resolved_pattern = search_pattern
        elif self.root is None:
            resolved_pattern = str(Path(search_pattern))
        else:
            resolved_pattern = str(self.root / search_pattern)

        matches = _glob(resolved_pattern, recursive=True)
        return tuple(sorted(path_to_file_uri(Path(match).resolve()) for match in matches))

    def _resolve_local_path(self, path: Path) -> Path:
        if path.is_absolute():
            return path
        if self.root is None:
            return Path(path).resolve(strict=False)
        return (self.root / path).resolve(strict=False)


__all__ = ["LocalFileSystemSource"]
