"""Public run-catalog facade."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from .models import CatalogIndexResult, ListRunsResult, RunComparison, RunFilter


class RunCatalog:
    """Facade for run collection catalog operations.

    Phase 1 establishes the stable import surface. Scanning, listing, SQLite
    storage, and comparison behavior are added by later v8 phases.
    """

    def __init__(self, collection_path: str | Path) -> None:
        self._collection_path = Path(collection_path)

    @property
    def collection_path(self) -> Path:
        """Return the local run collection path associated with this facade."""

        return self._collection_path

    @classmethod
    def open(cls, path: str | Path) -> "RunCatalog":
        """Open a run catalog facade for a local collection path."""

        return cls(path)

    def rebuild(self) -> CatalogIndexResult:
        """Rebuild the derived catalog from authoritative run-store metadata."""

        from ._sqlite import rebuild_catalog

        return rebuild_catalog(self.collection_path)

    def scan_current(self) -> ListRunsResult:
        """Directly scan the local collection for current run summaries."""

        from ._scan import scan_current_collection

        return scan_current_collection(self.collection_path)

    def list(self, filters: Sequence[RunFilter] = ()) -> ListRunsResult:
        """List current run summaries after refreshing the derived catalog."""

        from ._sqlite import list_current_catalog

        return list_current_catalog(self.collection_path, filters=filters)

    def compare(self, left: str, right: str) -> RunComparison:
        """Compare two current runs using persisted metadata only."""

        from ._compare import compare_current_runs

        current = self.list()
        return compare_current_runs(
            current.summaries,
            left_run_uri=left,
            right_run_uri=right,
            warnings=current.warnings,
        )


__all__ = ["RunCatalog"]
