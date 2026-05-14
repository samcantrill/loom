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
        "LOCAL_RUN_BUNDLE_ADAPTER",
        "RUN_BUNDLE_MANIFEST_MEMBER",
        "LocalRunBundleExporter",
        "build_portable_run_export_record",
        "export_completed_run_bundle",
        "export_run_bundle",
        "inspect_run_bundle",
        "normalize_bundle_member_path",
        "write_local_run_bundle",
        "OFFLINE_EVIDENCE_IMPORT_ADAPTER",
        "LocalRunBundleImporter",
        "OfflineEvidenceRunImporter",
        "build_offline_evidence_import_record",
        "build_portable_run_import_record",
        "import_offline_evidence",
        "import_run_bundle",
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
        "MigrationReadinessBlocker",
        "MigrationReadinessBlockerCode",
        "MigrationResumeReadiness",
        "PortableRunExportRecord",
        "PortableRunImportRecord",
        "PortableRunSourceIdentity",
        "PortableRunTargetIdentityPolicy",
        "RUN_BUNDLE_MANIFEST_KIND",
        "RUN_BUNDLE_MANIFEST_SCHEMA_VERSION",
        "RunAdapterIdentity",
        "RunBundleEntry",
        "RunBundleEntryKind",
        "RunBundleExportOptions",
        "RunBundleExportResult",
        "RunBundleFormatVersion",
        "RunBundleImportPolicy",
        "RunBundleInspection",
        "RunBundleImportResult",
        "RunBundleManifest",
        "RunBundlePayloadReference",
        "RunBundlePayloadSelection",
        "RunExchangeDiagnostic",
        "RunExchangeDiagnosticSeverity",
        "RunExchangeEnvelope",
        "RunExchangeOperationStatus",
        "RunExportResult",
        "RunImportCollisionPolicy",
        "RunImportChecksumPolicy",
        "RunImportMaterializationPolicy",
        "RunImportResumeMode",
        "RunExporter",
        "RunImporter",
        "RunTargetIdentityPolicyMode",
        "TransferRecordKind",
        "TransferVerificationCheck",
        "TransferVerificationRecord",
        "TransferVerificationStatus",
        "UnsupportedTransferRecord",
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
