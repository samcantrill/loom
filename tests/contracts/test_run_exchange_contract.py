"""Contract tests for portable run exchange contracts."""

from __future__ import annotations

from typing import Any, cast

import pytest

from loom.serialization import thaw_plain_data
from loom.runs import (
    CatalogValidationError,
    MigrationReadinessBlocker,
    MigrationReadinessBlockerCode,
    MigrationResumeReadiness,
    PortableRunSourceIdentity,
    PortableRunTargetIdentityPolicy,
    PortableRunExportRecord,
    PortableRunImportRecord,
    RUN_BUNDLE_MANIFEST_SCHEMA_VERSION,
    RUN_EXCHANGE_ARTIFACT_SUMMARIES_KEY,
    RunAdapterIdentity,
    RunBundleEntry,
    RunBundleEntryKind,
    RunBundleExportOptions,
    RunBundleExportResult,
    RunBundleInspection,
    RunBundleImportPolicy,
    RunBundleImportResult,
    RunBundleManifest,
    RunBundlePayloadReference,
    RunBundlePayloadSelection,
    RunExchangeDiagnostic,
    RunExchangeDiagnosticSeverity,
    RunExchangeEnvelope,
    RunExchangeOperationStatus,
    RunImportResumeMode,
    RunTargetIdentityPolicyMode,
    RunExporter,
    RunImporter,
    TransferRecordKind,
)


pytestmark = pytest.mark.contract


def _sample_manifest() -> RunBundleManifest:
    return RunBundleManifest(
        schema_version=RUN_BUNDLE_MANIFEST_SCHEMA_VERSION,
        run_uri="file:///runs/source/run-1",
        source_identity=PortableRunSourceIdentity(
            source_kind="local",
            run_uri="file:///runs/source/run-1",
        ),
        target_identity=PortableRunTargetIdentityPolicy(
            mode=RunTargetIdentityPolicyMode.TARGET_LOCAL,
            target_workspace_id="workspace-target",
        ),
        entries=(
            RunBundleEntry(
                entry_name="artifact.bin",
                kind=RunBundleEntryKind.PAYLOAD,
                path="artifact.bin",
            ),
        ),
        payload_refs=(
            RunBundlePayloadReference(
                entry_id="payload-1",
                uri="file:///runs/source/payloads/payload.bin",
            ),
        ),
        payload_selection=RunBundlePayloadSelection(include_artifacts=True),
        checksums={"artifact.bin": "sha256:abc"},
        diagnostics=(
            RunExchangeDiagnostic(
                code="contract.ok",
                message="manifest complete",
                severity=RunExchangeDiagnosticSeverity.INFO,
            ),
        ),
        warnings=(),
        extensions={"contract": {"scope": "manifest"}},
    )


def _sample_records() -> tuple[
    RunBundleManifest, PortableRunExportRecord, PortableRunImportRecord
]:
    manifest = _sample_manifest()
    adapter = RunAdapterIdentity(
        name="local-bundle",
        kind=TransferRecordKind.BUNDLE,
    )

    export_record = PortableRunExportRecord(
        source_identity=PortableRunSourceIdentity(
            source_kind="local",
            run_uri="file:///runs/source/run-1",
        ),
        adapter=adapter,
        selected_payload_refs=(
            RunBundlePayloadReference(
                entry_id="payload-1",
                uri="file:///runs/source/payload.bin",
            ),
        ),
        target_identity=PortableRunTargetIdentityPolicy(
            mode=RunTargetIdentityPolicyMode.TARGET_LOCAL,
            target_workspace_id="workspace-target",
        ),
        manifest=manifest,
        diagnostics=(
            RunExchangeDiagnostic(
                code="export",
                message="ok",
                severity=RunExchangeDiagnosticSeverity.INFO,
            ),
        ),
    )

    import_record = PortableRunImportRecord(
        source_identity=PortableRunSourceIdentity(
            source_kind="local",
            run_uri="file:///runs/source/run-1",
        ),
        adapter=adapter,
        manifest=manifest,
        selected_payload_refs=(
            RunBundlePayloadReference(
                entry_id="payload-1",
                uri="file:///runs/source/payload.bin",
            ),
        ),
        target_identity=PortableRunTargetIdentityPolicy(
            mode=RunTargetIdentityPolicyMode.TARGET_LOCAL,
            target_workspace_id="workspace-target",
        ),
        diagnostics=(
            RunExchangeDiagnostic(
                code="import",
                message="ok",
                severity=RunExchangeDiagnosticSeverity.INFO,
            ),
        ),
    )

    return manifest, export_record, import_record


def test_run_bundle_manifest_contract_shape() -> None:
    manifest = _sample_manifest()
    assert RunBundleManifest.from_dict(manifest.to_dict()) == manifest


def test_run_bundle_manifest_preserves_stage_15_extension_without_schema_revision() -> None:
    manifest = _sample_manifest()
    payload = cast(dict[str, Any], manifest.to_dict())
    extensions = cast(dict[str, Any], payload["extensions"])
    payload["extensions"] = {
        **extensions,
        RUN_EXCHANGE_ARTIFACT_SUMMARIES_KEY: {
            "schema_version": 1,
            "artifacts": [
                {
                    "artifact_name": "model",
                    "artifact_id": "external-model",
                    "uri": "s3://bucket/private/model",
                    "artifact_type": "model",
                    "codec_key": "json.v1",
                    "checksum": None,
                    "fingerprint": None,
                    "producer_stage": "train",
                    "summaries": {},
                }
            ],
        },
    }

    restored = RunBundleManifest.from_dict(payload)

    assert restored.schema_version == RUN_BUNDLE_MANIFEST_SCHEMA_VERSION
    assert (
        thaw_plain_data(restored.extensions[RUN_EXCHANGE_ARTIFACT_SUMMARIES_KEY])
        == payload["extensions"][RUN_EXCHANGE_ARTIFACT_SUMMARIES_KEY]
    )


def test_run_bundle_manifest_contract_rejects_unknown_fields() -> None:
    manifest_payload = _sample_manifest().to_dict()
    manifest_payload["unknown"] = True

    with pytest.raises(CatalogValidationError, match="unknown field"):
        RunBundleManifest.from_dict(manifest_payload)


def test_run_exchange_envelope_contract_round_trip() -> None:
    envelope = RunExchangeEnvelope(
        status=RunExchangeOperationStatus.FAILED,
        diagnostics=(
            RunExchangeDiagnostic(
                code="exchange.failed",
                message="exchange failed",
                severity=RunExchangeDiagnosticSeverity.ERROR,
            ),
        ),
        extensions={"source": "contract"},
    )
    assert RunExchangeEnvelope.from_dict(envelope.to_dict()) == envelope


def test_protocol_contract_shapes_are_structural() -> None:
    manifest, export_record, import_record = _sample_records()

    class GoodExporter:
        adapter = RunAdapterIdentity(
            name="contract-exporter",
            kind=TransferRecordKind.BUNDLE,
        )

        def export(
            self,
            record: PortableRunExportRecord,
            *,
            options: RunBundleExportOptions | None = None,
        ) -> RunBundleExportResult:
            assert record.manifest is not None
            assert options is None or isinstance(options, RunBundleExportOptions)
            return RunBundleExportResult(
                status=RunExchangeOperationStatus.SUCCEEDED,
                adapter=self.adapter,
                manifest=record.manifest,
                exported_payload_count=len(record.selected_payload_refs),
                diagnostics=(
                    RunExchangeDiagnostic(
                        code="ok",
                        message="exported",
                        severity=RunExchangeDiagnosticSeverity.INFO,
                    ),
                ),
            )

    class GoodImporter:
        adapter = RunAdapterIdentity(
            name="contract-importer",
            kind=TransferRecordKind.BUNDLE,
        )

        def inspect(
            self,
            record: PortableRunImportRecord,
            *,
            policy: RunBundleImportPolicy | None = None,
        ) -> RunBundleInspection:
            assert policy is None or isinstance(
                policy,
                (
                    RunBundleImportPolicy,
                    type(None),
                ),
            )
            return RunBundleInspection(
                status=RunExchangeOperationStatus.SUCCEEDED,
                manifest=record.manifest,
                included_payload_count=len(record.selected_payload_refs),
                diagnostics=(
                    RunExchangeDiagnostic(
                        code="inspect",
                        message="ok",
                        severity=RunExchangeDiagnosticSeverity.INFO,
                    ),
                ),
            )

        def import_record(
            self,
            record: PortableRunImportRecord,
            *,
            policy: RunBundleImportPolicy | None = None,
        ) -> RunBundleImportResult:
            return RunBundleImportResult(
                status=RunExchangeOperationStatus.SUCCEEDED,
                source_identity=record.source_identity,
                adapter=self.adapter,
                target_run_uri="file:///runs/target/run-1",
                imported_entry_count=len(record.manifest.entries),
                imported_payload_count=len(record.selected_payload_refs),
                readiness=MigrationResumeReadiness(
                    mode=RunImportResumeMode.HISTORICAL_ONLY,
                    blockers=(
                        MigrationReadinessBlocker(
                            code=MigrationReadinessBlockerCode.UNSUPPORTED_SOURCE_SCHEMA,
                            message="ready",
                        ),
                    ),
                ),
                transfer_verification=None,
                imported_source_payload_refs=(),
                diagnostics=(
                    RunExchangeDiagnostic(
                        code="import",
                        message="ok",
                        severity=RunExchangeDiagnosticSeverity.INFO,
                    ),
                ),
                import_provenance={"contract": "import"},
            )

    class MissingAdapter:
        def export(
            self,
            record: PortableRunExportRecord,
            *,
            options: RunBundleExportOptions | None = None,
        ) -> RunBundleExportResult:
            return RunBundleExportResult(
                status=RunExchangeOperationStatus.SUCCEEDED,
                adapter=RunAdapterIdentity(
                    name="fallback",
                    kind="fallback-exporter",
                ),
                exported_payload_count=0,
            )

        def inspect(
            self,
            record: PortableRunImportRecord,
            *,
            policy: RunBundleImportPolicy | None = None,
        ) -> RunBundleInspection:
            return RunBundleInspection(
                status=RunExchangeOperationStatus.SUCCEEDED,
                manifest=record.manifest,
                included_payload_count=0,
            )

        def import_record(
            self,
            record: PortableRunImportRecord,
            *,
            policy: RunBundleImportPolicy | None = None,
        ) -> RunBundleImportResult:
            return RunBundleImportResult(
                status=RunExchangeOperationStatus.SUCCEEDED,
                source_identity=record.source_identity,
                adapter=RunAdapterIdentity(
                    name="fallback",
                    kind="fallback-importer",
                ),
                target_run_uri=None,
                imported_entry_count=0,
                imported_payload_count=0,
                readiness=MigrationResumeReadiness(
                    mode=RunImportResumeMode.HISTORICAL_ONLY,
                    blockers=(
                        MigrationReadinessBlocker(
                            code=MigrationReadinessBlockerCode.MISSING_PAYLOAD,
                            message="missing payload",
                        ),
                    ),
                ),
                diagnostics=(),
                import_provenance={},
                transfer_verification=None,
                imported_source_payload_refs=(),
            )

    good_exporter = GoodExporter()
    good_importer = GoodImporter()
    assert isinstance(good_exporter, RunExporter)
    assert isinstance(good_importer, RunImporter)
    assert not isinstance(MissingAdapter(), RunImporter)
    assert not isinstance(MissingAdapter(), RunExporter)

    assert (
        good_exporter.export(export_record, options=None).status
        == RunExchangeOperationStatus.SUCCEEDED
    )
    assert good_importer.inspect(import_record).included_payload_count == 1
    assert (
        good_importer.import_record(import_record).source_identity == import_record.source_identity
    )
