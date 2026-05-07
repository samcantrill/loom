"""Run-store protocol contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from loom.artifacts import ArtifactRef
from loom.pipeline.events import PipelineEvent, PipelineEventRecord
from loom.pipeline.locks import RunLockRecord
from loom.pipeline.status import RunStatusRecord, StageStatusRecord
from loom.pipeline.stores.inspection import RunStateInspection
from loom.serialization import PlainData


@runtime_checkable
class RunLifecycleStore(Protocol):
    def create_run(
        self, run_uri: str, *, metadata: Mapping[str, PlainData] | None = None
    ) -> None: ...

    def open_run(self, run_uri: str) -> None: ...

    def resolve_run_uri(self, run_uri: str) -> str: ...

    def allocate_run_uri(self) -> str: ...


@runtime_checkable
class RunDocumentStore(Protocol):
    def read_run_document(self, run_uri: str) -> dict[str, PlainData]: ...

    def read_run_user_metadata(self, run_uri: str) -> dict[str, PlainData]: ...

    def write_run_user_metadata(
        self, run_uri: str, metadata: Mapping[str, PlainData]
    ) -> None: ...


@runtime_checkable
class RunStatusStore(Protocol):
    def read_run_status(self, run_uri: str) -> RunStatusRecord | None: ...

    def write_run_status(self, run_uri: str, status: RunStatusRecord) -> None: ...


@runtime_checkable
class RunPlanStore(Protocol):
    def read_plan(self, run_uri: str) -> dict[str, PlainData] | None: ...

    def write_plan(self, run_uri: str, plan: Mapping[str, PlainData]) -> None: ...


@runtime_checkable
class RunArtifactIndexStore(Protocol):
    def read_artifact_index(self, run_uri: str) -> dict[str, ArtifactRef]: ...

    def write_artifact_index(
        self, run_uri: str, index: Mapping[str, ArtifactRef]
    ) -> None: ...


@runtime_checkable
class RunConfigStore(Protocol):
    def read_config_snapshot(self, run_uri: str, name: str) -> str | None: ...

    def write_config_snapshot(self, run_uri: str, name: str, content: str) -> None: ...

    def read_composition_manifest(
        self, run_uri: str
    ) -> dict[str, PlainData] | None: ...

    def write_composition_manifest(
        self, run_uri: str, manifest: Mapping[str, PlainData]
    ) -> None: ...

    def read_recipe_manifest(
        self, run_uri: str
    ) -> tuple[dict[str, PlainData], ...] | None: ...

    def write_recipe_manifest(
        self, run_uri: str, records: Sequence[Mapping[str, PlainData]]
    ) -> None: ...


@runtime_checkable
class RunProvenanceStore(Protocol):
    def read_provenance_document(
        self, run_uri: str, name: str
    ) -> dict[str, PlainData] | None: ...

    def write_provenance_document(
        self, run_uri: str, name: str, document: Mapping[str, PlainData]
    ) -> None: ...


@runtime_checkable
class RunEventStore(Protocol):
    def append_event(
        self, run_uri: str, event: PipelineEvent
    ) -> PipelineEventRecord: ...

    def read_events(self, run_uri: str) -> tuple[PipelineEventRecord, ...]: ...


@runtime_checkable
class RunLockStore(Protocol):
    def acquire_run_lock(
        self,
        run_uri: str,
        *,
        owner: Mapping[str, PlainData] | None = None,
    ) -> RunLockRecord: ...

    def read_run_lock(self, run_uri: str) -> RunLockRecord | None: ...

    def release_run_lock(self, run_uri: str, token: str) -> None: ...


@runtime_checkable
class RunInspectionStore(Protocol):
    def list_run_stages(self, run_uri: str) -> tuple[str, ...]: ...

    def inspect_run_state(self, run_uri: str) -> RunStateInspection: ...


@runtime_checkable
class StageStateStore(Protocol):
    def read_stage_status(
        self, run_uri: str, stage_name: str
    ) -> StageStatusRecord | None: ...

    def write_stage_status(
        self, run_uri: str, stage_name: str, status: StageStatusRecord
    ) -> None: ...

    def read_stage_inputs(
        self, run_uri: str, stage_name: str
    ) -> dict[str, ArtifactRef] | None: ...

    def write_stage_inputs(
        self,
        run_uri: str,
        stage_name: str,
        inputs: Mapping[str, ArtifactRef],
        *,
        attempt: int,
    ) -> None: ...

    def read_stage_outputs(
        self, run_uri: str, stage_name: str
    ) -> dict[str, ArtifactRef] | None: ...

    def write_stage_outputs(
        self,
        run_uri: str,
        stage_name: str,
        outputs: Mapping[str, ArtifactRef],
        *,
        attempt: int,
    ) -> None: ...

    def read_stage_fingerprint(
        self, run_uri: str, stage_name: str
    ) -> dict[str, PlainData] | None: ...

    def write_stage_fingerprint(
        self,
        run_uri: str,
        stage_name: str,
        fingerprint: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None: ...

    def read_stage_failure(
        self, run_uri: str, stage_name: str
    ) -> dict[str, PlainData] | None: ...

    def write_stage_failure(
        self,
        run_uri: str,
        stage_name: str,
        failure: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None: ...

    def read_stage_provenance(
        self, run_uri: str, stage_name: str
    ) -> dict[str, PlainData] | None: ...

    def write_stage_provenance(
        self,
        run_uri: str,
        stage_name: str,
        provenance: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None: ...


@runtime_checkable
class StageLogStore(Protocol):
    def read_stage_log(
        self, run_uri: str, stage_name: str, stream: str
    ) -> str | None: ...

    def write_stage_log(
        self, run_uri: str, stage_name: str, stream: str, content: str
    ) -> None: ...


@runtime_checkable
class StageWorkspaceStore(Protocol):
    def prepare_stage_workspace(self, run_uri: str, stage_name: str) -> None: ...


@runtime_checkable
class LocalRunStorePaths(Protocol):
    def resolve_run_uri(self, run_uri: str) -> str: ...

    def allocate_run_uri(self) -> str: ...

    def local_run_dir(self, run_uri: str) -> Path: ...

    def local_stage_dir(self, run_uri: str, stage_name: str) -> Path: ...

    def local_artifact_root(self, run_uri: str) -> Path: ...

    def local_stage_artifact_dir(self, run_uri: str, stage_name: str) -> Path: ...

    def local_config_path(self, run_uri: str, name: str) -> Path: ...

    def local_provenance_path(self, run_uri: str, name: str) -> Path: ...

    def local_stage_log_path(
        self, run_uri: str, stage_name: str, stream: str
    ) -> Path: ...

    def local_stage_workspace_dir(self, run_uri: str, stage_name: str) -> Path: ...


@runtime_checkable
class RunStore(
    RunLifecycleStore,
    RunDocumentStore,
    RunStatusStore,
    RunPlanStore,
    RunArtifactIndexStore,
    RunConfigStore,
    RunProvenanceStore,
    RunEventStore,
    RunLockStore,
    RunInspectionStore,
    StageStateStore,
    StageLogStore,
    StageWorkspaceStore,
    Protocol,
): ...
