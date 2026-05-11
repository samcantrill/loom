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
        "RunArtifactStore",
        "StageArtifactStore",
        "LocalArtifactStore",
        "LocalRunArtifactStore",
        "LocalStageArtifactStore",
        "PerRunAuthorityStore",
        "RunStore",
        "StageStore",
        "AuthorityStoreError",
        "StatusTransition",
        "AttemptAllocation",
        "OutputCommit",
        "AUTHORITY_MUTATION_ROUTE_PREFIX",
        "AUTHORITY_MUTATION_RUN_ADMIT_PATH",
        "AUTHORITY_MUTATION_OPEN_RUN_PATH",
        "AUTHORITY_MUTATION_RUN_TRANSITION_PATH",
        "AUTHORITY_MUTATION_STAGE_TRANSITION_PATH",
        "AUTHORITY_MUTATION_ALLOCATE_STAGE_ATTEMPT_PATH",
        "AUTHORITY_MUTATION_RECORD_OUTPUT_COMMIT_PATH",
        "AuthorityClient",
        "AuthorityClientError",
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
        "LOOM_AUTHORITY_MODE",
        "AuthorityResolutionError",
        "AuthorityResolutionMode",
        "AuthorityReferenceSource",
        "AuthorityServiceHealthState",
        "AuthorityResolutionOutcomeKind",
        "AuthorityResolutionFailureKind",
        "AuthorityResolutionDiagnosticSeverity",
        "AuthorityResolverDiagnostic",
        "AuthorityRegistryHint",
        "AuthorityServiceHealth",
        "AuthorityResolverInput",
        "AuthorityResolutionResult",
        "resolve_authority",
        "authority_resolution_mode_from_env",
        "authority_resolution_mode_from_mapping",
        "authority_resolution_mode_to_env",
        "AUTHORITY_PROTOCOL_VERSION",
        "AuthorityProtocolError",
        "AuthorityProtocolOperationKind",
        "AuthorityProtocolErrorCategory",
        "AuthorityReadinessState",
        "AuthorityProtocolVersion",
        "AuthorityProtocolMetadata",
        "AuthorityProtocolRequest",
        "AuthorityProtocolReadiness",
        "AuthorityProtocolResult",
        "AuthorityProtocolRejection",
        "AuthorityProtocolResponse",
        "accepted_authority_response",
        "rejected_authority_response",
        "protocol_versions_compatible",
        "AuthorityBackendKind",
        "AuthorityDeploymentProfile",
        "AuthorityReference",
        "AuthorityConfig",
        "AuthorityConfigError",
        "authority_config_from_env",
        "authority_config_from_mapping",
        "authority_config_to_cli_args",
        "authority_config_to_env",
        "default_deployment_profile_for_backend",
        "RequiredAuthorityCapability",
        "CapabilityAdmissionResult",
        "CapabilityAdmissionError",
        "AuthorityAdmissionError",
        "admit_authority_capabilities",
        "create_run_store",
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
        "coordination_requirement_diagnostics",
        "AuthorityDeploymentError",
        "AuthorityDeploymentPreflightResult",
        "AuthorityDeploymentProfileSummary",
        "describe_authority_deployment",
        "preflight_authority_deployment",
        "DEFERRED_RESULT_ENVELOPE_SCHEMA_VERSION",
        "DeferredFinalizationError",
        "DeferredReconciliationCode",
        "DeferredReconciliationResult",
        "DeferredResultEnvelope",
        "reconcile_deferred_result",
        "LegacyRunStore",
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
        "AuthoritativeReadOptions",
        "CompletedRunBundleMetadata",
        "LocalMaterializationRequest",
        "MaterializationReadModelError",
        "artifact_payload_ref",
        "collect_local_materialized_refs",
        "read_authoritative_run",
        "read_completed_run_bundle_metadata",
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
    assert "admit_run" in stores.RunStore.__dict__
    assert "stage_store" in stores.RunStore.__dict__
    assert "allocate_attempt" in stores.StageStore.__dict__
    assert "record_output_commit" in stores.StageStore.__dict__
    assert "acquire_trial_lease" in stores.WorkspaceCoordinationStore.__dict__
    assert "acquire_resource_lease" in stores.WorkspaceCoordinationStore.__dict__
    assert "renew_lease" in stores.WorkspaceCoordinationStore.__dict__
    assert "fail_lease" in stores.WorkspaceCoordinationStore.__dict__
    assert "set_counter_limit" in stores.WorkspaceCoordinationStore.__dict__
    assert "read_prepared_run" in stores.RunPreparedRunStore.__dict__
    assert "write_prepared_run" in stores.RunPreparedRunStore.__dict__
    assert "read_run_freshness" in stores.RunFreshnessStore.__dict__
    assert "local_stage_worker_request_path" in stores.LocalRunStorePaths.__dict__
    assert "local_stage_worker_result_path" in stores.LocalRunStorePaths.__dict__
    assert "local_generated_artifact_path" in stores.LocalRunStorePaths.__dict__
    assert "local_run_freshness_path" in stores.LocalRunStorePaths.__dict__
    assert "read_stage_status" not in stores.RunArtifactStore.__dict__
    assert "write_stage_status" not in stores.StageArtifactStore.__dict__
    assert "write_submitted_operation" not in stores.RunArtifactStore.__dict__
    assert "record_output_commit" not in stores.StageArtifactStore.__dict__
    write_signature = inspect.signature(
        stores.RunConfigStore.write_composition_manifest
    )
    assert list(write_signature.parameters) == ["self", "run_uri", "manifest"]


@pytest.mark.parametrize(
    "forbidden",
    [
        "loom.config",
        "loom.runs",
        "loom.cli",
        "sqlite3",
        "fastapi",
        "starlette",
        "pydantic",
        "loom.pipeline.stores.service_authority",
        "loom.pipeline.stores.sqlite_authority",
        "loom.pipeline.stores.sqlite_coordination",
    ],
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
