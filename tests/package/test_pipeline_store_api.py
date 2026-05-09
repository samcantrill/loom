"""Package-level API tests for pipeline store modules."""

import inspect
import subprocess
import sys

import pytest


pytestmark = pytest.mark.package


def test_pipeline_store_public_exports() -> None:
    import loom.pipeline.stores as stores

    assert stores
    assert set(stores.__all__) == {
        "ArtifactStore",
        "LocalArtifactStore",
        "PerRunAuthorityStore",
        "AuthorityStoreError",
        "StatusTransition",
        "AttemptAllocation",
        "OutputCommit",
        "BackendCapability",
        "CapabilityScope",
        "CapabilitySupport",
        "DiagnosticSeverity",
        "UnsupportedCapabilityCode",
        "BackendCapabilityRecord",
        "BackendCapabilitySet",
        "UnsupportedCapability",
        "StoreDiagnostic",
        "AuthorityCapabilityError",
        "AUTHORITY_SCHEMA_VERSION",
        "AuthoritySchemaError",
        "AuthoritySchemaFailureKind",
        "AuthoritySchemaFailure",
        "AuthoritySchemaCheck",
        "check_authority_schema_version",
        "AuthorityModelError",
        "LeaseKind",
        "LeaseState",
        "MaterializedRefKind",
        "CleanupCandidateKind",
        "RecoveryKind",
        "StaticOutcomeKind",
        "ReadModelWarningCode",
        "BackendRevision",
        "LifecycleReason",
        "StageAttempt",
        "LeaseRecord",
        "OutputCommitRecord",
        "ArtifactFactRecord",
        "MaterializedRef",
        "CleanupCandidate",
        "RecoveryRecord",
        "StaticOutcomeRecord",
        "ReadModelWarning",
        "StageLifecycleSnapshot",
        "AuthoritativeRunSnapshot",
        "WorkspaceCoordinationStore",
        "CoordinationStoreError",
        "TrialState",
        "WorkspaceIdentity",
        "SweepIdentity",
        "TrialReference",
        "TrialLeaseRecord",
        "ResourceLeaseRecord",
        "CoordinationRecoveryRecord",
        "ConcurrencyCounter",
        "RunStore",
        "RunLifecycleStore",
        "RunDocumentStore",
        "RunFreshnessStore",
        "RunFreshnessRecord",
        "RunFreshnessError",
        "RunEventStore",
        "RunInspectionStore",
        "RunLockStore",
        "RunStatusStore",
        "RunPlanStore",
        "RunPreparedRunStore",
        "RunArtifactIndexStore",
        "RunConfigStore",
        "RunProvenanceStore",
        "RunRuntimeMetadataStore",
        "RunSubmittedOperationStore",
        "StageStateStore",
        "StageLogStore",
        "StageWorkspaceStore",
        "LocalRunStorePaths",
        "LocalRunStore",
        "RunStageInspection",
        "RunStateInspection",
        "StoreError",
        "ArtifactStoreError",
        "RunStoreError",
        "PreparedRunStorePayloadError",
        "RunLockError",
        "RunLockConflictError",
        "RunLockReleaseError",
        "UnsafeStorePathError",
        "InvalidRunURIError",
        "UnsupportedArtifactURIError",
        "ArtifactNotFoundError",
        "MissingArtifactCodecError",
        "ArtifactTypeMismatchError",
        "ArtifactChecksumMismatchError",
        "ArtifactChecksumUnsupportedError",
        "RunAlreadyExistsError",
        "RunNotFoundError",
        "MissingStoreDocumentError",
        "CorruptStoreDocumentError",
        "StageStateNotFoundError",
        "AtomicWriteError",
        "ensure_dir",
        "unique_temp_path",
        "atomic_write_bytes",
        "atomic_write_text",
        "atomic_write_json",
        "replace_file",
        "format_artifact_key",
        "parse_artifact_key",
        "artifact_index_to_dict",
        "artifact_index_from_dict",
        "merge_artifact_index",
        "LocalRunURI",
        "resolve_local_run_uri",
        "validate_run_uri",
        "run_uri_to_path",
        "path_to_run_uri",
        "allocate_local_run_uri",
    }
    assert "read_composition_manifest" in stores.RunConfigStore.__dict__
    assert "write_composition_manifest" in stores.RunConfigStore.__dict__
    assert "read_stage_worker_request" in stores.StageStateStore.__dict__
    assert "write_stage_worker_request" in stores.StageStateStore.__dict__
    assert "read_stage_worker_result" in stores.StageStateStore.__dict__
    assert "write_stage_worker_result" in stores.StageStateStore.__dict__
    assert "allocate_stage_attempt" in stores.PerRunAuthorityStore.__dict__
    assert "record_output_commit" in stores.PerRunAuthorityStore.__dict__
    assert "acquire_trial_lease" in stores.WorkspaceCoordinationStore.__dict__
    assert "acquire_resource_lease" in stores.WorkspaceCoordinationStore.__dict__
    assert "read_prepared_run" in stores.RunPreparedRunStore.__dict__
    assert "write_prepared_run" in stores.RunPreparedRunStore.__dict__
    assert "read_run_freshness" in stores.RunFreshnessStore.__dict__
    assert "local_stage_worker_request_path" in stores.LocalRunStorePaths.__dict__
    assert "local_stage_worker_result_path" in stores.LocalRunStorePaths.__dict__
    assert "local_generated_artifact_path" in stores.LocalRunStorePaths.__dict__
    assert "local_run_freshness_path" in stores.LocalRunStorePaths.__dict__
    write_signature = inspect.signature(
        stores.RunConfigStore.write_composition_manifest
    )
    assert list(write_signature.parameters) == ["self", "run_uri", "manifest"]


@pytest.mark.parametrize(
    "forbidden",
    ["loom.config", "loom.runs", "loom.cli", "sqlite3"],
)
def test_pipeline_stores_import_does_not_import_forbidden_modules(
    forbidden: str,
) -> None:
    script = (
        "import sys\n"
        "import loom.pipeline.stores\n"
        f"if {forbidden!r} in sys.modules:\n"
        f"    raise SystemExit('{forbidden} was imported through loom.pipeline.stores')\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
