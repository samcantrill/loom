"""Contract tests for source protocol implementations."""

from collections.abc import Mapping
from pathlib import Path

from loom.io.sources import DataSource, LocalFileSystemSource


class DummySource:
    """Downstream-style source implementation."""

    name = "dummy"

    def supports(self, uri: str | Path) -> bool:
        return isinstance(uri, str)

    def resolve(self, uri: str | Path) -> Path:
        return Path(uri)

    def open(self, uri: str | Path, mode: str = "rb", *, encoding: str = "utf-8"):
        if "b" in mode:
            return open(uri, mode)  # type: ignore[call-arg]
        return open(uri, mode, encoding=encoding)  # pragma: no cover - behavioral smoke only

    def exists(self, uri: str | Path) -> bool:
        return self.resolve(uri).exists()

    def stat(self, uri: str | Path) -> Mapping[str, object]:
        return {"uri": str(uri), "backend": self.name, "exists": self.exists(uri), "size": None, "mtime": None}

    def glob(self, pattern: str | Path) -> tuple[str, ...]:
        return tuple()


def test_downstream_source_satisfies_protocol() -> None:
    assert isinstance(DummySource(), DataSource)


def test_local_source_satisfies_protocol() -> None:
    assert isinstance(LocalFileSystemSource(), DataSource)
