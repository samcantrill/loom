"""Contract tests for store protocols."""

from collections.abc import Mapping, Sequence
from pathlib import Path

from loom.artifacts import ArtifactRef
from loom.diagnostics.inspection import inspect_run_artifact, inspect_run_artifacts
from loom.pipeline.events import EventScope, PipelineEvent, PipelineEventRecord
from loom.pipeline.locks import RunLockRecord
from loom.pipeline import RunStatusRecord, StageStatusRecord
from loom.pipeline.stores import (
    ArtifactStore,
    LocalArtifactStore,
    LocalRunStore,
    LocalRunStorePaths,
    RunArtifactIndexStore,
    RunConfigStore,
    RunDocumentStore,
    RunEventStore,
    RunInspectionStore,
    RunLockStore,
    RunLifecycleStore,
    RunProvenanceStore,
    RunPlanStore,
    RunStore,
    RunStateInspection,
    RunStatusStore,
    StageLogStore,
    StageStateStore,
    StageWorkspaceStore,
    path_to_run_uri,
)
from loom.serialization import PlainData


class DummyArtifactStore:
    def save(
        self,
        obj: object,
        *,
        stage_name: str,
        name: str,
        artifact_type: str,
        codec_key: str,
        schema_version: int = 1,
        metadata: Mapping[str, PlainData] | None = None,
        fingerprint: str | None = None,
    ) -> ArtifactRef:
        return ArtifactRef(artifact_id="s/o", uri="file:///tmp/x", artifact_type="json")

    def register(
        self,
        uri: str,
        *,
        stage_name: str,
        name: str,
        artifact_type: str,
        codec_key: str | None = None,
        schema_version: int = 1,
        metadata: Mapping[str, PlainData] | None = None,
        fingerprint: str | None = None,
        checksum: str | None = None,
        allow_external: bool = False,
    ) -> ArtifactRef:
        return ArtifactRef(artifact_id="s/o", uri="file:///tmp/x", artifact_type="json")

    def load(
        self,
        ref: ArtifactRef,
        *,
        expected_type: str | None = None,
        codec_key: str | None = None,
    ) -> object:
        return {}

    def exists(self, ref: ArtifactRef) -> bool:
        return True

    def verify_checksum(self, ref: ArtifactRef) -> bool:
        return True

    def validate(self, ref: ArtifactRef, *, expected_type: str | None = None) -> None:
        return None


class DummyRunStore:
    def resolve_run_uri(self, run_uri: str) -> str:
        return run_uri

    def allocate_run_uri(self) -> str:
        return "file:///tmp/loom-runs/run-1"

    def create_run(
        self, run_uri: str, *, metadata: Mapping[str, PlainData] | None = None
    ) -> None:
        return None

    def open_run(self, run_uri: str) -> None:
        return None

    def read_run_document(self, run_uri: str) -> dict[str, PlainData]:
        return {}

    def read_run_user_metadata(self, run_uri: str) -> dict[str, PlainData]:
        return {}

    def write_run_user_metadata(
        self, run_uri: str, metadata: Mapping[str, PlainData]
    ) -> None:
        return None

    def read_run_status(self, run_uri: str) -> RunStatusRecord | None:
        return None

    def write_run_status(self, run_uri: str, status: RunStatusRecord) -> None:
        return None

    def read_plan(self, run_uri: str) -> dict[str, PlainData] | None:
        return None

    def write_plan(self, run_uri: str, plan: Mapping[str, PlainData]) -> None:
        return None

    def read_artifact_index(self, run_uri: str) -> dict[str, ArtifactRef]:
        return {}

    def write_artifact_index(
        self, run_uri: str, index: Mapping[str, ArtifactRef]
    ) -> None:
        return None

    def read_config_snapshot(self, run_uri: str, name: str) -> str | None:
        return None

    def write_config_snapshot(self, run_uri: str, name: str, content: str) -> None:
        return None

    def read_composition_manifest(self, run_uri: str) -> dict[str, PlainData] | None:
        return {"schema_version": 1}

    def write_composition_manifest(
        self, run_uri: str, manifest: Mapping[str, PlainData]
    ) -> None:
        return None

    def read_recipe_manifest(
        self, run_uri: str
    ) -> tuple[dict[str, PlainData], ...] | None:
        return None

    def write_recipe_manifest(
        self, run_uri: str, records: Sequence[Mapping[str, PlainData]]
    ) -> None:
        return None

    def read_provenance_document(
        self, run_uri: str, name: str
    ) -> dict[str, PlainData] | None:
        return {}

    def write_provenance_document(
        self, run_uri: str, name: str, document: Mapping[str, PlainData]
    ) -> None:
        return None

    def append_event(self, run_uri: str, event: PipelineEvent) -> PipelineEventRecord:
        return PipelineEventRecord(
            run_uri=run_uri,
            sequence=1,
            timestamp="2020-01-01T00:00:00Z",
            scope=EventScope.run(),
            event_type=event.event_type,
            payload=event.payload,
        )

    def read_events(self, run_uri: str) -> tuple[PipelineEventRecord, ...]:
        return ()

    def acquire_run_lock(
        self,
        run_uri: str,
        *,
        owner: Mapping[str, PlainData] | None = None,
    ) -> RunLockRecord:
        return RunLockRecord(
            run_uri=run_uri,
            token="token",
            acquired_at="2020-01-01T00:00:00Z",
            owner=owner or {},
        )

    def read_run_lock(self, run_uri: str) -> RunLockRecord | None:
        return None

    def release_run_lock(self, run_uri: str, token: str) -> None:
        return None

    def list_run_stages(self, run_uri: str) -> tuple[str, ...]:
        return ()

    def inspect_run_state(self, run_uri: str) -> RunStateInspection:
        return RunStateInspection(run_uri=run_uri)

    def read_stage_status(
        self, run_uri: str, stage_name: str
    ) -> StageStatusRecord | None:
        return None

    def write_stage_status(
        self, run_uri: str, stage_name: str, status: StageStatusRecord
    ) -> None:
        return None

    def read_stage_inputs(
        self, run_uri: str, stage_name: str
    ) -> dict[str, ArtifactRef] | None:
        return None

    def write_stage_inputs(
        self,
        run_uri: str,
        stage_name: str,
        inputs: Mapping[str, ArtifactRef],
        *,
        attempt: int,
    ) -> None:
        return None

    def read_stage_outputs(
        self, run_uri: str, stage_name: str
    ) -> dict[str, ArtifactRef] | None:
        return None

    def write_stage_outputs(
        self,
        run_uri: str,
        stage_name: str,
        outputs: Mapping[str, ArtifactRef],
        *,
        attempt: int,
    ) -> None:
        return None

    def read_stage_fingerprint(
        self, run_uri: str, stage_name: str
    ) -> dict[str, PlainData] | None:
        return None

    def write_stage_fingerprint(
        self,
        run_uri: str,
        stage_name: str,
        fingerprint: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None:
        return None

    def read_stage_failure(
        self, run_uri: str, stage_name: str
    ) -> dict[str, PlainData] | None:
        return None

    def write_stage_failure(
        self,
        run_uri: str,
        stage_name: str,
        failure: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None:
        return None

    def read_stage_provenance(
        self, run_uri: str, stage_name: str
    ) -> dict[str, PlainData] | None:
        return None

    def write_stage_provenance(
        self,
        run_uri: str,
        stage_name: str,
        provenance: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None:
        return None

    def read_stage_log(self, run_uri: str, stage_name: str, stream: str) -> str | None:
        return None

    def write_stage_log(
        self, run_uri: str, stage_name: str, stream: str, content: str
    ) -> None:
        return None

    def prepare_stage_workspace(self, run_uri: str, stage_name: str) -> None:
        return None


class IncompleteArtifactStore:
    def save(self, *_: object, **__: object) -> object:
        raise NotImplementedError


class IncompleteRunStore:
    def create_run(self, run_uri: str) -> None:
        return None


class DummyRunStorePaths:
    def resolve_run_uri(self, run_uri: str) -> str:
        return run_uri

    def allocate_run_uri(self) -> str:
        return "file:///tmp/loom-runs/run-1"

    def local_run_dir(self, run_uri: str) -> Path:
        return Path(run_uri)

    def local_stage_dir(self, run_uri: str, stage_name: str) -> Path:
        return Path(run_uri) / stage_name

    def local_artifact_root(self, run_uri: str) -> Path:
        return Path(run_uri) / "artifacts"

    def local_stage_artifact_dir(self, run_uri: str, stage_name: str) -> Path:
        return Path(run_uri) / "artifacts" / stage_name

    def local_config_path(self, run_uri: str, name: str) -> Path:
        return Path(run_uri) / f"{name}.yaml"

    def local_provenance_path(self, run_uri: str, name: str) -> Path:
        return Path(run_uri) / f"{name}.json"

    def local_stage_log_path(self, run_uri: str, stage_name: str, stream: str) -> Path:
        return Path(run_uri) / stage_name / f"{stream}.log"

    def local_stage_workspace_dir(self, run_uri: str, stage_name: str) -> Path:
        return Path(run_uri) / stage_name / "workspace"


class TrackingArtifactDiagnosticsStore:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def open_run(self, run_uri: str) -> None:
        self.calls.append(f"open_run:{run_uri}")

    def read_artifact_index(self, run_uri: str) -> dict[str, ArtifactRef]:
        self.calls.append(f"read_artifact_index:{run_uri}")
        return {
            "build.data": ArtifactRef(
                artifact_id="build/data",
                uri="file:///tmp/run/artifacts/build/data.json",
                artifact_type="json",
                codec_key="json.v1",
                producer_stage="build",
            )
        }

    def read_stage_provenance(
        self,
        run_uri: str,
        stage_name: str,
    ) -> dict[str, PlainData] | None:
        self.calls.append(f"read_stage_provenance:{run_uri}:{stage_name}")
        return {"tool": "loom"}


def test_local_artifact_store_satisfies_protocol() -> None:
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as run_root:
        assert isinstance(LocalArtifactStore(root=Path(run_root)), ArtifactStore)


def test_fake_artifact_store_matches_protocol() -> None:
    assert isinstance(DummyArtifactStore(), ArtifactStore)


def test_fake_run_store_matches_protocol() -> None:
    assert isinstance(DummyRunStore(), RunLifecycleStore)
    assert isinstance(DummyRunStore(), RunDocumentStore)
    assert isinstance(DummyRunStore(), RunStatusStore)
    assert isinstance(DummyRunStore(), RunPlanStore)
    assert isinstance(DummyRunStore(), RunArtifactIndexStore)
    assert isinstance(DummyRunStore(), RunConfigStore)
    assert isinstance(DummyRunStore(), RunProvenanceStore)
    assert isinstance(DummyRunStore(), RunEventStore)
    assert isinstance(DummyRunStore(), RunInspectionStore)
    assert isinstance(DummyRunStore(), RunLockStore)
    assert isinstance(DummyRunStore(), StageStateStore)
    assert isinstance(DummyRunStore(), StageLogStore)
    assert isinstance(DummyRunStore(), StageWorkspaceStore)
    assert isinstance(DummyRunStore(), RunStore)
    assert DummyRunStore().read_composition_manifest("file:///tmp/run1") == {
        "schema_version": 1
    }


def test_local_run_store_matches_expanded_protocols(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "run1")

    assert isinstance(store, RunEventStore)
    assert isinstance(store, RunInspectionStore)
    assert isinstance(store, RunLockStore)
    assert isinstance(store, RunStore)
    assert store.resolve_run_uri(run_uri) == run_uri


def test_fake_run_store_does_not_satisfy_local_paths() -> None:
    assert not isinstance(DummyRunStore(), LocalRunStorePaths)


def test_fake_local_run_store_paths_matches_protocol() -> None:
    assert isinstance(DummyRunStorePaths(), LocalRunStorePaths)


def test_artifact_diagnostics_use_public_run_store_readers() -> None:
    run_uri = "file:///tmp/run"
    list_store = TrackingArtifactDiagnosticsStore()

    summary = inspect_run_artifacts(run_uri, run_store=list_store)

    assert summary.artifacts[0].key == "build.data"
    assert summary.artifacts[0].artifact_id == "build/data"
    assert list_store.calls == [
        f"open_run:{run_uri}",
        f"read_artifact_index:{run_uri}",
        f"read_stage_provenance:{run_uri}:build",
    ]

    show_store = TrackingArtifactDiagnosticsStore()
    detail = inspect_run_artifact(run_uri, "build/data", run_store=show_store)

    assert detail.stage_provenance == {"tool": "loom"}
    assert show_store.calls == [
        f"open_run:{run_uri}",
        f"read_artifact_index:{run_uri}",
        f"read_stage_provenance:{run_uri}:build",
        f"read_stage_provenance:{run_uri}:build",
    ]


def test_structural_protocol_rejects_incomplete_implementations() -> None:
    assert not isinstance(IncompleteArtifactStore(), ArtifactStore)
    assert not isinstance(IncompleteRunStore(), RunStore)
