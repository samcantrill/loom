"""Explicit services consumed by pipeline execution."""

from __future__ import annotations

from dataclasses import dataclass

from loom.pipeline.stores import AuthorityConfig, LocalRunStorePaths
from loom.pipeline.stores.authority import PerRunAuthorityStore
from loom.pipeline.stores.coordination import WorkspaceCoordinationStore
from loom.pipeline.stores.run_store import (
    RunArtifactIndexStore,
    RunConfigStore,
    RunDocumentStore,
    RunEventObserverLinkStore,
    RunEventSinkFailureStore,
    RunEventStore,
    RunFreshnessStore,
    RunInspectionStore,
    RunLifecycleStore,
    RunLockStore,
    RunPlanStore,
    RunPreparedRunStore,
    RunProvenanceStore,
    RunReliabilityStore,
    RunRuntimeMetadataStore,
    RunStatusStore,
    RunSubmittedOperationStore,
    StageLogStore,
    StageStateStore,
    StageWorkerResultStore,
    StageWorkspaceStore,
)


@dataclass(frozen=True, slots=True)
class RuntimeServices:
    """Narrow runtime dependencies plus explicit deployment facts."""

    lifecycle: RunLifecycleStore
    documents: RunDocumentStore
    freshness: RunFreshnessStore
    run_status: RunStatusStore
    plans: RunPlanStore
    prepared_runs: RunPreparedRunStore
    artifact_index: RunArtifactIndexStore
    config: RunConfigStore
    provenance: RunProvenanceStore
    events: RunEventStore
    event_sink_failures: RunEventSinkFailureStore
    event_observer_links: RunEventObserverLinkStore
    locks: RunLockStore
    inspection: RunInspectionStore
    runtime_metadata: RunRuntimeMetadataStore
    submitted_operations: RunSubmittedOperationStore
    reliability: RunReliabilityStore
    stage_state: StageStateStore
    stage_logs: StageLogStore
    stage_workspaces: StageWorkspaceStore
    worker_results: StageWorkerResultStore
    local_paths: LocalRunStorePaths
    authority_config: AuthorityConfig | None = None
    authority_store: PerRunAuthorityStore | None = None
    coordination_store: WorkspaceCoordinationStore | None = None
    workspace_id: str | None = None
    owner_id: str | None = None

    def __post_init__(self) -> None:
        for name, protocol in (
            ("lifecycle", RunLifecycleStore),
            ("documents", RunDocumentStore),
            ("freshness", RunFreshnessStore),
            ("run_status", RunStatusStore),
            ("plans", RunPlanStore),
            ("prepared_runs", RunPreparedRunStore),
            ("artifact_index", RunArtifactIndexStore),
            ("config", RunConfigStore),
            ("provenance", RunProvenanceStore),
            ("events", RunEventStore),
            ("event_sink_failures", RunEventSinkFailureStore),
            ("event_observer_links", RunEventObserverLinkStore),
            ("locks", RunLockStore),
            ("inspection", RunInspectionStore),
            ("runtime_metadata", RunRuntimeMetadataStore),
            ("submitted_operations", RunSubmittedOperationStore),
            ("reliability", RunReliabilityStore),
            ("stage_state", StageStateStore),
            ("stage_logs", StageLogStore),
            ("stage_workspaces", StageWorkspaceStore),
            ("worker_results", StageWorkerResultStore),
            ("local_paths", LocalRunStorePaths),
        ):
            if not isinstance(getattr(self, name), protocol):
                raise TypeError(
                    f"RuntimeServices.{name} must satisfy {protocol.__name__}"
                )
        if self.authority_config is not None and not isinstance(
            self.authority_config, AuthorityConfig
        ):
            raise TypeError("RuntimeServices.authority_config must be AuthorityConfig")
        if self.authority_store is not None and not isinstance(
            self.authority_store, PerRunAuthorityStore
        ):
            raise TypeError(
                "RuntimeServices.authority_store must satisfy PerRunAuthorityStore"
            )
        if self.coordination_store is not None and not isinstance(
            self.coordination_store, WorkspaceCoordinationStore
        ):
            raise TypeError(
                "RuntimeServices.coordination_store must satisfy WorkspaceCoordinationStore"
            )
        for name, value in (
            ("workspace_id", self.workspace_id),
            ("owner_id", self.owner_id),
        ):
            if value is not None and (not isinstance(value, str) or not value):
                raise TypeError(f"RuntimeServices.{name} must be a non-empty string")



__all__ = ["RuntimeServices"]
