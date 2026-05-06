"""Contract tests for store protocols."""

from collections.abc import Mapping, Sequence
from pathlib import Path

from loom.artifacts import ArtifactRef
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
    RunLockStore,
    RunLifecycleStore,
    RunProvenanceStore,
    RunPlanStore,
    RunStore,
    RunStatusStore,
    StageLogStore,
    StageStateStore,
    StageWorkspaceStore,
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
    def create_run(
        self, run_id: str, *, metadata: Mapping[str, PlainData] | None = None
    ) -> None:
        return None

    def open_run(self, run_id: str) -> None:
        return None

    def read_run_document(self, run_id: str) -> dict[str, PlainData]:
        return {}

    def read_run_user_metadata(self, run_id: str) -> dict[str, PlainData]:
        return {}

    def write_run_user_metadata(
        self, run_id: str, metadata: Mapping[str, PlainData]
    ) -> None:
        return None

    def read_run_status(self, run_id: str) -> RunStatusRecord | None:
        return None

    def write_run_status(self, run_id: str, status: RunStatusRecord) -> None:
        return None

    def read_plan(self, run_id: str) -> dict[str, PlainData] | None:
        return None

    def write_plan(self, run_id: str, plan: Mapping[str, PlainData]) -> None:
        return None

    def read_artifact_index(self, run_id: str) -> dict[str, ArtifactRef]:
        return {}

    def write_artifact_index(
        self, run_id: str, index: Mapping[str, ArtifactRef]
    ) -> None:
        return None

    def read_config_snapshot(self, run_id: str, name: str) -> str | None:
        return None

    def write_config_snapshot(self, run_id: str, name: str, content: str) -> None:
        return None

    def read_composition_manifest(self, run_id: str) -> dict[str, PlainData] | None:
        return {"schema_version": 1}

    def write_composition_manifest(
        self, run_id: str, manifest: Mapping[str, PlainData]
    ) -> None:
        return None

    def read_recipe_manifest(
        self, run_id: str
    ) -> tuple[dict[str, PlainData], ...] | None:
        return None

    def write_recipe_manifest(
        self, run_id: str, records: Sequence[Mapping[str, PlainData]]
    ) -> None:
        return None

    def read_provenance_document(
        self, run_id: str, name: str
    ) -> dict[str, PlainData] | None:
        return {}

    def write_provenance_document(
        self, run_id: str, name: str, document: Mapping[str, PlainData]
    ) -> None:
        return None

    def append_event(self, run_id: str, event: PipelineEvent) -> PipelineEventRecord:
        return PipelineEventRecord(
            run_id=run_id,
            sequence=1,
            timestamp="2020-01-01T00:00:00Z",
            scope=EventScope.run(),
            event_type=event.event_type,
            payload=event.payload,
        )

    def read_events(self, run_id: str) -> tuple[PipelineEventRecord, ...]:
        return ()

    def acquire_run_lock(
        self,
        run_id: str,
        *,
        owner: Mapping[str, PlainData] | None = None,
    ) -> RunLockRecord:
        return RunLockRecord(
            run_id=run_id,
            token="token",
            acquired_at="2020-01-01T00:00:00Z",
            owner=owner or {},
        )

    def read_run_lock(self, run_id: str) -> RunLockRecord | None:
        return None

    def release_run_lock(self, run_id: str, token: str) -> None:
        return None

    def read_stage_status(
        self, run_id: str, stage_name: str
    ) -> StageStatusRecord | None:
        return None

    def write_stage_status(
        self, run_id: str, stage_name: str, status: StageStatusRecord
    ) -> None:
        return None

    def read_stage_inputs(
        self, run_id: str, stage_name: str
    ) -> dict[str, ArtifactRef] | None:
        return None

    def write_stage_inputs(
        self,
        run_id: str,
        stage_name: str,
        inputs: Mapping[str, ArtifactRef],
        *,
        attempt: int,
    ) -> None:
        return None

    def read_stage_outputs(
        self, run_id: str, stage_name: str
    ) -> dict[str, ArtifactRef] | None:
        return None

    def write_stage_outputs(
        self,
        run_id: str,
        stage_name: str,
        outputs: Mapping[str, ArtifactRef],
        *,
        attempt: int,
    ) -> None:
        return None

    def read_stage_fingerprint(
        self, run_id: str, stage_name: str
    ) -> dict[str, PlainData] | None:
        return None

    def write_stage_fingerprint(
        self,
        run_id: str,
        stage_name: str,
        fingerprint: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None:
        return None

    def read_stage_failure(
        self, run_id: str, stage_name: str
    ) -> dict[str, PlainData] | None:
        return None

    def write_stage_failure(
        self,
        run_id: str,
        stage_name: str,
        failure: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None:
        return None

    def read_stage_provenance(
        self, run_id: str, stage_name: str
    ) -> dict[str, PlainData] | None:
        return None

    def write_stage_provenance(
        self,
        run_id: str,
        stage_name: str,
        provenance: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None:
        return None

    def read_stage_log(self, run_id: str, stage_name: str, stream: str) -> str | None:
        return None

    def write_stage_log(
        self, run_id: str, stage_name: str, stream: str, content: str
    ) -> None:
        return None

    def prepare_stage_workspace(self, run_id: str, stage_name: str) -> None:
        return None


class IncompleteArtifactStore:
    def save(self, *_: object, **__: object) -> object:
        raise NotImplementedError


class IncompleteRunStore:
    def create_run(self, run_id: str) -> None:
        return None


class DummyRunStorePaths:
    def local_run_dir(self, run_id: str) -> Path:
        return Path(run_id)

    def local_stage_dir(self, run_id: str, stage_name: str) -> Path:
        return Path(run_id) / stage_name

    def local_artifact_root(self, run_id: str) -> Path:
        return Path(run_id) / "artifacts"

    def local_stage_artifact_dir(self, run_id: str, stage_name: str) -> Path:
        return Path(run_id) / "artifacts" / stage_name

    def local_config_path(self, run_id: str, name: str) -> Path:
        return Path(run_id) / f"{name}.yaml"

    def local_provenance_path(self, run_id: str, name: str) -> Path:
        return Path(run_id) / f"{name}.json"

    def local_stage_log_path(self, run_id: str, stage_name: str, stream: str) -> Path:
        return Path(run_id) / stage_name / f"{stream}.log"

    def local_stage_workspace_dir(self, run_id: str, stage_name: str) -> Path:
        return Path(run_id) / stage_name / "workspace"


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
    assert isinstance(DummyRunStore(), RunLockStore)
    assert isinstance(DummyRunStore(), StageStateStore)
    assert isinstance(DummyRunStore(), StageLogStore)
    assert isinstance(DummyRunStore(), StageWorkspaceStore)
    assert isinstance(DummyRunStore(), RunStore)
    assert DummyRunStore().read_composition_manifest("run1") == {"schema_version": 1}


def test_local_run_store_matches_expanded_protocols(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")

    assert isinstance(store, RunEventStore)
    assert isinstance(store, RunLockStore)
    assert isinstance(store, RunStore)


def test_fake_run_store_does_not_satisfy_local_paths() -> None:
    assert not isinstance(DummyRunStore(), LocalRunStorePaths)


def test_fake_local_run_store_paths_matches_protocol() -> None:
    assert isinstance(DummyRunStorePaths(), LocalRunStorePaths)


def test_structural_protocol_rejects_incomplete_implementations() -> None:
    assert not isinstance(IncompleteArtifactStore(), ArtifactStore)
    assert not isinstance(IncompleteRunStore(), RunStore)
