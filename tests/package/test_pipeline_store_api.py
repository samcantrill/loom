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
        "ARTIFACT_STORE_BACKEND_CONTRACT_VERSION",
        "ArtifactStoreBackendDescriptor",
        "ArtifactStoreBackendDiagnostic",
        "ArtifactStoreBackendDiagnosticSeverity",
        "ArtifactStoreBackendError",
        "ArtifactStoreBackendFactory",
        "ArtifactStoreBackendHandler",
        "ArtifactStoreBackendPayloadHandler",
        "ArtifactStoreBackendOperation",
        "ArtifactStoreBackendOperationResult",
        "ArtifactStoreBackendRegistry",
        "ArtifactStoreBackendRegistryError",
        "ArtifactStoreBackendVersionError",
        "ArtifactStoreCapabilities",
        "ArtifactStoreCapabilityRecord",
        "ArtifactStoreCapabilitySupport",
        "ArtifactStorePayloadOperationRequest",
        "ArtifactStorePayloadOperationResult",
        "artifact_store_backend_versions_compatible",
        "normalize_artifact_store_backend_kind",
        "ImmutableArtifactSemanticsError",
        "ImmutableArtifactValidationResult",
        "ImmutableArtifactValidationTarget",
        "admit_artifact_store_operation",
        "admit_artifact_store_operations",
        "artifact_ref_from_external_declaration",
        "artifact_ref_from_published_record",
        "evaluate_immutable_artifact_lookup",
        "lookup_immutable_artifact",
        "validate_external_artifact_declaration",
        "validate_published_artifact_record",
        "LocalArtifactStore",
        "LocalRunArtifactStore",
        "LocalStageArtifactStore",
        "ArtifactMaterializationError",
        "LocalMaterializationPolicy",
        "ArtifactMaterializationRequest",
        "ArtifactMaterializationResult",
        "materialize_artifact_locally",
        "artifact_materialization_location",
        "artifact_materialized_ref",
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
        "AUTHORITY_MUTATION_OFFLINE_IMPORT_PATH",
        "AUTHORITY_COORDINATION_WORKSPACE_CREATE_PATH",
        "AUTHORITY_COORDINATION_SWEEP_CREATE_PATH",
        "AUTHORITY_COORDINATION_TRIAL_RECORD_PATH",
        "AUTHORITY_COORDINATION_TRIAL_LIST_PATH",
        "AUTHORITY_COORDINATION_TRIAL_LEASE_ACQUIRE_PATH",
        "AUTHORITY_COORDINATION_LEASE_RENEW_PATH",
        "AUTHORITY_COORDINATION_LEASE_RELEASE_PATH",
        "AUTHORITY_COORDINATION_LEASE_FAIL_PATH",
        "AUTHORITY_COORDINATION_COUNTER_LIMIT_SET_PATH",
        "AUTHORITY_COORDINATION_COUNTER_INCREMENT_PATH",
        "AUTHORITY_COORDINATION_COUNTER_DECREMENT_PATH",
        "AUTHORITY_COORDINATION_COUNTER_READ_PATH",
        "AUTHORITY_COORDINATION_RECOVERY_SCAN_PATH",
        "AUTHORITY_COORDINATION_RESOURCE_LEASE_ACQUIRE_PATH",
        "AUTHORITY_COORDINATION_RESOURCE_LIMIT_READ_PATH",
        "AUTHORITY_COORDINATION_RESOURCE_LIMIT_SET_PATH",
        "AuthorityClient",
        "AuthorityClientError",
        "DEFAULT_AUTHORITY_READINESS_TIMEOUT_SECONDS",
        "AuthorityFactoryError",
        "AuthorityFactoryResolution",
        "config_from_authority_reference",
        "create_authority_client",
        "probe_http_authority_readiness",
        "require_online_authority",
        "resolve_authority_for_factory",
        "AUTHORITY_REGISTRY_ALLOCATIONS_DIR",
        "AUTHORITY_REGISTRY_CURRENT_FILE",
        "AUTHORITY_REGISTRY_DIR",
        "AUTHORITY_REGISTRY_SCHEMA_VERSION",
        "AuthorityRegistryAllocationScope",
        "AuthorityRegistryError",
        "AuthorityRegistryRecord",
        "AuthorityRegistryValidationResult",
        "AuthorityRegistryValidationStatus",
        "authority_registry_dir",
        "authority_registry_hint_from_record",
        "authority_registry_record_path",
        "authority_service_health_from_record",
        "read_authority_registry_record",
        "validate_authority_registry",
        "validate_authority_registry_record",
        "write_authority_registry_record",
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
        "ReliabilityPolicyScope",
        "BackendRevision",
        "LifecycleReason",
        "StageAttempt",
        "LeaseRecord",
        "OutputCommitRecord",
        "ArtifactFactRecord",
        "MaterializedRef",
        "CleanupCandidate",
        "CleanupReportFact",
        "CleanupResultFact",
        "RecoveryRecord",
        "StaticOutcomeRecord",
        "ReliabilityPolicyFact",
        "ReadModelWarning",
        "StageLifecycleSnapshot",
        "AuthoritativeRunSnapshot",
        "WorkspaceCoordinationStore",
        "ServiceWorkspaceCoordinationStore",
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
        "RunEventSinkFailureStore",
        "RunEventObserverLinkStore",
        "RunInspectionStore",
        "RunLockStore",
        "RunStatusStore",
        "RunPlanStore",
        "RunPreparedRunStore",
        "RunArtifactIndexStore",
        "RunConfigStore",
        "RunProvenanceStore",
        "RunRuntimeMetadataStore",
        "RunReliabilityStore",
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
    assert "read_resource_limit" in stores.WorkspaceCoordinationStore.__dict__
    assert "renew_lease" in stores.WorkspaceCoordinationStore.__dict__
    assert "fail_lease" in stores.WorkspaceCoordinationStore.__dict__
    assert "set_counter_limit" in stores.WorkspaceCoordinationStore.__dict__
    assert "read_prepared_run" in stores.RunPreparedRunStore.__dict__
    assert "write_prepared_run" in stores.RunPreparedRunStore.__dict__
    assert "read_run_freshness" in stores.RunFreshnessStore.__dict__
    assert "append_event_sink_failure" in stores.RunEventSinkFailureStore.__dict__
    assert "read_event_sink_failures" in stores.RunEventSinkFailureStore.__dict__
    assert "append_event_observer_link" in stores.RunEventObserverLinkStore.__dict__
    assert "read_event_observer_links" in stores.RunEventObserverLinkStore.__dict__
    assert "write_reliability_status_detail" in stores.RunReliabilityStore.__dict__
    assert "write_stage_attempt_transaction" in stores.RunReliabilityStore.__dict__
    assert "list_retry_decisions" in stores.RunReliabilityStore.__dict__
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
        "weave",
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
