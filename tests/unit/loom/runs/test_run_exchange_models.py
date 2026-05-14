"""Unit tests for run exchange model contracts."""

from __future__ import annotations

import pytest

from loom.runs import (
    CatalogValidationError,
    MigrationResumeReadiness,
    RUN_BUNDLE_MANIFEST_SCHEMA_VERSION,
    PortableRunSourceIdentity,
    PortableRunTargetIdentityPolicy,
    RunBundleEntry,
    RunBundleEntryKind,
    RunBundleExportOptions,
    RunBundleManifest,
    RunBundlePayloadReference,
    RunBundlePayloadSelection,
    RunExchangeDiagnostic,
    RunExchangeDiagnosticSeverity,
    RunTargetIdentityPolicyMode,
)


def _sample_manifest() -> RunBundleManifest:
    return RunBundleManifest(
        schema_version=RUN_BUNDLE_MANIFEST_SCHEMA_VERSION,
        run_uri="file:///runs/source/run-1",
        source_identity=PortableRunSourceIdentity(
            source_kind="local",
            run_uri="file:///runs/source/run-1",
            extensions={"source": {"mode": "unit"}},
        ),
        target_identity=PortableRunTargetIdentityPolicy(
            mode=RunTargetIdentityPolicyMode.TARGET_LOCAL,
            target_workspace_id="workspace-target",
        ),
        entries=(
            RunBundleEntry(
                entry_name="manifest.json",
                kind=RunBundleEntryKind.METADATA,
                path="manifest.json",
                metadata={"kind": "manifest"},
            ),
        ),
        payload_refs=(
            RunBundlePayloadReference(
                entry_id="payload-1",
                uri="file:///runs/source/run-1/payloads/payload.bin",
            ),
        ),
        payload_selection=RunBundlePayloadSelection(
            include_artifacts=True,
            include_logs=False,
        ),
        checksums={"manifest.json": "sha256:aa"},
        diagnostics=(
            RunExchangeDiagnostic(
                code="run_manifest.ok",
                message="manifest validated",
                severity=RunExchangeDiagnosticSeverity.INFO,
            ),
        ),
        warnings=(),
        extensions={"local": {"tag": "exchange"}},
    )


def test_run_bundle_manifest_is_strict_round_trip_with_extensions() -> None:
    manifest = _sample_manifest()
    payload = manifest.to_dict()

    restored = RunBundleManifest.from_dict(payload)

    assert restored == manifest
    assert restored.extensions == manifest.extensions
    assert restored.payload_selection.include_artifacts is True


def test_payload_and_export_defaults_are_metadata_only() -> None:
    assert RunBundlePayloadSelection().to_dict() == {
        "include_artifacts": False,
        "include_logs": False,
        "include_workspace": False,
        "include_other": False,
        "extensions": {},
    }
    assert RunBundleExportOptions().to_dict() == {
        "include_payloads": False,
        "include_logs": False,
        "include_workspace": False,
        "include_non_terminal_runs": False,
        "verify_checksums": False,
        "max_payload_count": None,
        "extensions": {},
    }


def test_run_bundle_manifest_rejects_unknown_field() -> None:
    payload = _sample_manifest().to_dict()
    payload["unexpected"] = "field"

    with pytest.raises(CatalogValidationError, match="unknown field"):
        RunBundleManifest.from_dict(payload)


def test_run_bundle_manifest_rejects_unsupported_schema_version() -> None:
    payload = _sample_manifest().to_dict()
    payload["schema_version"] = RUN_BUNDLE_MANIFEST_SCHEMA_VERSION + 1

    with pytest.raises(
        CatalogValidationError,
        match="unsupported manifest schema_version",
    ):
        RunBundleManifest.from_dict(payload)


def test_run_exchange_readiness_records_round_trip() -> None:
    blockers = MigrationResumeReadiness(
        mode="historical_only",
        blockers=(),
    )

    assert blockers.to_dict() == {
        "mode": "historical_only",
        "blockers": [],
    }
    assert MigrationResumeReadiness.from_dict(blockers.to_dict()) == blockers
