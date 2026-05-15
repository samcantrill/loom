"""Contract coverage for transfer evidence and unsupported adapters."""

from __future__ import annotations

from loom.queue import LaunchContract
from loom.runs import (
    MigrationReadinessBlocker,
    MigrationReadinessBlockerCode,
    MigrationResumeReadiness,
    PortableRunExportRecord,
    PortableRunImportRecord,
    PortableRunSourceIdentity,
    PortableRunTargetIdentityPolicy,
    RUN_BUNDLE_MANIFEST_SCHEMA_VERSION,
    RunAdapterIdentity,
    RunBundleExportOptions,
    RunBundleExportResult,
    RunBundleInspection,
    RunBundleImportPolicy,
    RunBundleImportResult,
    RunBundleManifest,
    RunExchangeOperationStatus,
    RunExportResult,
    RunExporter,
    RunImportResumeMode,
    RunImporter,
    RunTargetIdentityPolicyMode,
    TransferRecordKind,
    TransferVerificationCheck,
    TransferVerificationRecord,
    TransferVerificationStatus,
    transfer_verification_to_delegated_verification,
    unsupported_transfer_diagnostic,
    unsupported_transfer_verification,
)


def test_transfer_verification_is_queue_consumable_plain_data() -> None:
    verification = unsupported_transfer_verification(
        _adapter("object-store"),
        "object-store transfer is not implemented",
    )

    contract = LaunchContract(
        adapter="slurm",
        entrypoint="sbatch",
        delegated_verification=transfer_verification_to_delegated_verification(
            verification
        ),
    )

    delegated = contract.to_dict()["delegated_verification"]
    assert delegated == {
        "portable_run_transfer": {
            "status": "unsupported",
            "reason": "object-store transfer is not implemented",
            "adapter": _adapter("object-store").to_dict(),
            "checks": [verification.checks[0].to_dict()],
            "summary": {
                "proven": [],
                "unproven": [],
                "unsupported": ["transfer_supported"],
                "proven_count": 0,
                "unproven_count": 0,
                "unsupported_count": 1,
            },
            "details": {"reason": "object-store transfer is not implemented"},
        }
    }
    assert LaunchContract.from_dict(contract.to_dict()) == contract


def test_fake_importer_and_exporter_can_attach_transfer_verification() -> None:
    manifest = _manifest()
    export_record = PortableRunExportRecord(
        source_identity=manifest.source_identity,
        adapter=_adapter("fake"),
        manifest=manifest,
    )
    import_record = PortableRunImportRecord(
        source_identity=manifest.source_identity,
        adapter=_adapter("fake"),
        manifest=manifest,
    )
    exporter = FakeExporter()
    importer = FakeImporter()

    assert isinstance(exporter, RunExporter)
    assert isinstance(importer, RunImporter)
    export_result = exporter.export(export_record)
    import_result = importer.import_record(import_record)

    assert export_result.transfer_verification is not None
    assert export_result.transfer_verification.status is TransferVerificationStatus.PROVEN
    assert import_result.transfer_verification is not None
    assert import_result.transfer_verification.status is TransferVerificationStatus.UNPROVEN


def test_unsupported_exporter_returns_structured_diagnostic() -> None:
    adapter = _adapter("remote-provider")
    exporter = UnsupportedExporter(adapter)
    manifest = _manifest(adapter=adapter)
    export_record = PortableRunExportRecord(
        source_identity=manifest.source_identity,
        adapter=adapter,
        manifest=manifest,
    )

    result = exporter.export(export_record)

    assert result.status is RunExchangeOperationStatus.FAILED
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "run_transfer.unsupported"
    ]
    assert result.transfer_verification is not None
    assert result.transfer_verification.status is TransferVerificationStatus.UNSUPPORTED


def _adapter(name: str) -> RunAdapterIdentity:
    kind = TransferRecordKind.FAKE if name == "fake" else TransferRecordKind.UNKNOWN
    return RunAdapterIdentity(name=name, version="1", kind=kind)


class FakeExporter:
    adapter = _adapter("fake")

    def export(
        self,
        record: PortableRunExportRecord,
        *,
        options: RunBundleExportOptions | None = None,
    ) -> RunBundleExportResult:
        del options
        return RunExportResult(
            status=RunExchangeOperationStatus.SUCCEEDED,
            adapter=self.adapter,
            manifest=record.manifest,
            exported_payload_count=0,
            transfer_verification=TransferVerificationRecord(
                adapter=self.adapter,
                status=TransferVerificationStatus.PROVEN,
                checks=(
                    TransferVerificationCheck(
                        name="fake_transfer",
                        status=TransferVerificationStatus.PROVEN,
                        message="fake transfer is proven",
                    ),
                ),
            ),
        )


class FakeImporter:
    adapter = _adapter("fake")

    def inspect(
        self,
        record: PortableRunImportRecord,
        *,
        policy: RunBundleImportPolicy | None = None,
    ) -> RunBundleInspection:
        del policy
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
        del policy
        return RunBundleImportResult(
            status=RunExchangeOperationStatus.SUCCEEDED,
            source_identity=record.source_identity,
            adapter=self.adapter,
            target_run_uri="file:///target/run",
            imported_entry_count=0,
            imported_payload_count=0,
            readiness=MigrationResumeReadiness(
                mode=RunImportResumeMode.HISTORICAL_ONLY,
                blockers=(
                    MigrationReadinessBlocker(
                        code=MigrationReadinessBlockerCode.HISTORICAL_ONLY_POLICY,
                        message="historical only",
                    ),
                ),
            ),
            transfer_verification=TransferVerificationRecord(
                adapter=self.adapter,
                status=TransferVerificationStatus.UNPROVEN,
                checks=(
                    TransferVerificationCheck(
                        name="fake_import",
                        status=TransferVerificationStatus.UNPROVEN,
                        message="fake import is unproven",
                    ),
                ),
            ),
        )


class UnsupportedExporter:
    def __init__(self, adapter: RunAdapterIdentity) -> None:
        self.adapter = adapter

    def export(
        self,
        record: PortableRunExportRecord,
        *,
        options: RunBundleExportOptions | None = None,
    ) -> RunBundleExportResult:
        del options
        reason = "remote-provider transfer is not implemented"
        return RunBundleExportResult(
            status=RunExchangeOperationStatus.FAILED,
            adapter=self.adapter,
            manifest=record.manifest,
            exported_payload_count=0,
            diagnostics=(unsupported_transfer_diagnostic(self.adapter, reason),),
            transfer_verification=unsupported_transfer_verification(
                self.adapter,
                reason,
            ),
        )


def _manifest(adapter: RunAdapterIdentity | None = None) -> RunBundleManifest:
    selected = adapter or _adapter("fake")
    source = PortableRunSourceIdentity(
        source_kind=selected.kind,
        run_uri="file:///runs/source/run-1",
    )
    return RunBundleManifest(
        schema_version=RUN_BUNDLE_MANIFEST_SCHEMA_VERSION,
        run_uri="file:///runs/source/run-1",
        source_identity=source,
        target_identity=PortableRunTargetIdentityPolicy(
            mode=RunTargetIdentityPolicyMode.TARGET_LOCAL
        ),
    )
