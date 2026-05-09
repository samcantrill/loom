"""Public run-catalog facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import ListRunsResult
from .errors import CatalogFeatureUnavailableError


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

    def rebuild(self) -> Any:
        """Rebuild the derived catalog.

        Implemented in a later v8 phase.
        """

        raise CatalogFeatureUnavailableError(
            "RunCatalog.rebuild is implemented in a later v8 phase"
        )

    def scan_current(self) -> ListRunsResult:
        """Directly scan the local collection for current run summaries."""

        from ._scan import scan_current_collection

        return scan_current_collection(self.collection_path)

    def list(self, *args: Any, **kwargs: Any) -> Any:
        """List current run summaries.

        Implemented in a later v8 phase.
        """

        raise CatalogFeatureUnavailableError(
            "RunCatalog.list is implemented in a later v8 phase"
        )

    def compare(self, *args: Any, **kwargs: Any) -> Any:
        """Compare two runs using persisted metadata.

        Implemented in a later v8 phase.
        """

        raise CatalogFeatureUnavailableError(
            "RunCatalog.compare is implemented in a later v8 phase"
        )


__all__ = ["RunCatalog"]
