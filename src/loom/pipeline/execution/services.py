"""Explicit services consumed by pipeline execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from loom.pipeline.stores import AuthorityConfig, LocalRunStorePaths
from loom.pipeline.stores.authority import PerRunAuthorityStore
from loom.pipeline.stores.coordination import WorkspaceCoordinationStore
from loom.pipeline.stores.run_store import (
    LegacyRunStore,
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

    @classmethod
    def from_legacy(cls, run_store: LegacyRunStore) -> "RuntimeServices":
        """Unpack the transitional aggregate at the sole compatibility boundary."""

        if not isinstance(run_store, LegacyRunStore):
            raise TypeError("run_store must satisfy LegacyRunStore")
        if not isinstance(run_store, LocalRunStorePaths):
            raise TypeError("run_store must satisfy LocalRunStorePaths")
        raw_config = getattr(run_store, "authority_config", None)
        config = raw_config() if callable(raw_config) else raw_config
        return cls(
            lifecycle=run_store,
            documents=run_store,
            freshness=run_store,
            run_status=run_store,
            plans=run_store,
            prepared_runs=run_store,
            artifact_index=run_store,
            config=run_store,
            provenance=run_store,
            events=run_store,
            event_sink_failures=run_store,
            event_observer_links=run_store,
            locks=run_store,
            inspection=run_store,
            runtime_metadata=run_store,
            submitted_operations=run_store,
            reliability=cast(RunReliabilityStore, run_store),
            stage_state=run_store,
            stage_logs=run_store,
            stage_workspaces=run_store,
            worker_results=run_store,
            local_paths=run_store,
            authority_config=cast(AuthorityConfig | None, config),
            authority_store=cast(
                PerRunAuthorityStore | None,
                getattr(run_store, "authority_store", None),
            ),
            coordination_store=getattr(run_store, "workspace_coordination_store", None),
            workspace_id=cast(str | None, getattr(run_store, "workspace_id", None)),
            owner_id=cast(str | None, getattr(run_store, "owner_id", None)),
        )


__all__ = ["RuntimeServices"]
