"""Package-level API tests for run catalog imports."""

from __future__ import annotations

import subprocess
import sys
from textwrap import dedent

import pytest


pytestmark = pytest.mark.package


def test_runs_public_exports_are_stable() -> None:
    import loom.runs as runs

    assert runs.__all__ == [
        "RunCatalog",
        "CatalogError",
        "CatalogFeatureUnavailableError",
        "CatalogStorageError",
        "CatalogValidationError",
        "ArtifactSummary",
        "CATALOG_WARNING_CODES",
        "CatalogIndexResult",
        "CatalogWarning",
        "CatalogWarningCode",
        "ComparisonEntry",
        "ComparisonSection",
        "ComparisonStatus",
        "ListRunsResult",
        "RunComparison",
        "RunFilter",
        "RunFilterKind",
        "RunSummary",
        "StageSummary",
        "SubmittedOperationSummary",
    ]
    assert runs.RunCatalog.open("runs").collection_path.name == "runs"


def test_runs_import_is_lightweight() -> None:
    script = dedent(
        """
        import sys

        import loom.runs
        from loom.runs import RunCatalog

        for forbidden in (
            "loom.cli",
            "loom.pipeline.execution",
            "loom.pipeline.executors",
            "loom.pipeline.stores.local_runs",
            "sqlite3",
            "yaml",
            "omegaconf",
            "pydantic",
            "project",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.runs")
        assert RunCatalog
        print("ok")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
