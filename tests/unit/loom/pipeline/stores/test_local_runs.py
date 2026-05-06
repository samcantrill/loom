"""Unit tests for local run-store behavior."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline.events import EventScope, PipelineEvent
from loom.pipeline import RunStatus, StageStatus
from loom.pipeline.status import RunStatusRecord, StageStatusRecord
from loom.pipeline.stores import (
    CorruptStoreDocumentError,
    LocalRunStore,
    RunLockConflictError,
    RunLockReleaseError,
    RunNotFoundError,
    UnsafeStorePathError,
    atomic_write_json,
)
from loom.serialization import PlainData


def _artifact_ref(*, artifact_id: str = "stage/out") -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        uri="file:///tmp/stage/out.json",
        artifact_type="json",
        codec_key="json.v1",
    )


def test_local_run_creation_writes_layout(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    store.create_run("run1", metadata={"project": "demo"})
    run_dir = store.local_run_dir("run1")

    assert run_dir.exists()
    assert (run_dir / "config").is_dir()
    assert (run_dir / "provenance").is_dir()
    assert (run_dir / "stages").is_dir()
    assert (run_dir / "artifacts").is_dir()
    assert (run_dir / "run.json").is_file()


def test_open_run_validates_required_run_metadata(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    store.create_run("run1")
    store.open_run("run1")


def test_local_run_metadata_optional_reads(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    store.create_run("run1", metadata={"a": 1})
    metadata = store.read_run_document("run1")
    assert metadata["run_id"] == "run1"
    assert metadata["metadata"] == {"a": 1}
    assert store.read_plan("run1") is None
    assert store.read_artifact_index("run1") == {}
    assert store.read_events("run1") == ()


def test_local_run_appends_and_reads_events(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    store.create_run("run1")

    first = store.append_event(
        "run1",
        PipelineEvent(
            scope=EventScope.run(),
            event_type="run.created",
            payload={"source": "test"},
            timestamp="2020-01-01T00:00:00Z",
        ),
    )
    second = store.append_event(
        "run1",
        PipelineEvent(scope=EventScope.stage("build"), event_type="stage.started"),
    )

    assert first.sequence == 1
    assert second.sequence == 2
    assert [record.sequence for record in store.read_events("run1")] == [1, 2]
    assert store.read_events("run1")[0].payload == {"source": "test"}
    assert (store.local_run_dir("run1") / "events.jsonl").read_text(
        encoding="utf-8"
    ).count("\n") == 2


def test_local_run_rejects_corrupt_event_log(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    store.create_run("run1")
    path = store.local_run_dir("run1") / "events.jsonl"
    path.write_text(
        '{"schema_version":1,"run_id":"run1","sequence":2,"timestamp":"2020-01-01T00:00:00Z","scope":{"kind":"RUN","stage_name":null},"event_type":"run.created","payload":{}}\n',
        encoding="utf-8",
    )

    with pytest.raises(CorruptStoreDocumentError) as exc_info:
        store.read_events("run1")
    assert "sequence gap" in str(exc_info.value)
    assert f"{path}:1" in str(exc_info.value)


def test_local_run_acquires_reads_and_releases_lock(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    store.create_run("run1")

    record = store.acquire_run_lock("run1", owner={"worker": "unit"})

    assert record.run_id == "run1"
    assert record.token
    assert record.owner["metadata"] == {"worker": "unit"}
    assert isinstance(record.owner["pid"], int)
    assert isinstance(record.owner["hostname"], str)
    assert store.read_run_lock("run1") == record
    assert (store.local_run_dir("run1") / "lock.json").exists()

    store.release_run_lock("run1", record.token)

    assert store.read_run_lock("run1") is None
    assert not (store.local_run_dir("run1") / "lock.json").exists()


def test_local_run_lock_conflict_and_release_errors_preserve_lock(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    store.create_run("run1")
    record = store.acquire_run_lock("run1")

    with pytest.raises(RunLockConflictError):
        store.acquire_run_lock("run1")

    with pytest.raises(RunLockReleaseError, match="mismatch"):
        store.release_run_lock("run1", "wrong-token")

    assert store.read_run_lock("run1") == record


def test_local_run_lock_requires_existing_run(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")

    with pytest.raises(RunNotFoundError):
        store.acquire_run_lock("missing")


def test_local_run_rejects_corrupt_lock_document(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    store.create_run("run1")
    lock_path = store.local_run_dir("run1") / "lock.json"
    lock_path.write_text('{"schema_version":1,"run_id":"other"}\n', encoding="utf-8")

    with pytest.raises(CorruptStoreDocumentError):
        store.read_run_lock("run1")
    with pytest.raises(RunLockReleaseError):
        store.release_run_lock("run1", "token")


def test_local_run_status_plan_and_artifacts(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    store.create_run("run1")

    status = RunStatusRecord(
        run_id="run1",
        status=RunStatus.CREATED,
        created_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:00Z",
    )
    store.write_run_status("run1", status)
    assert store.read_run_status("run1") == status

    plan_payload: dict[str, PlainData] = {"stage": ["a", "b"]}
    store.write_plan("run1", plan_payload)
    assert store.read_plan("run1") == plan_payload

    ref = ArtifactRef(
        artifact_id="stage/output",
        uri="file:///tmp/stage/output.json",
        artifact_type="json",
        codec_key="json.v1",
    )
    store.write_artifact_index("run1", {"stage.output": ref})
    assert store.read_artifact_index("run1") == {"stage.output": ref}


def test_local_run_snapshots_and_provenance(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    store.create_run("run1")

    store.write_config_snapshot("run1", "raw", "a: b\n")
    assert store.read_config_snapshot("run1", "raw") == "a: b\n"
    manifest: dict[str, PlainData] = {
        "source_artifacts": [{"kind": "config", "path": "config.yaml"}],
        "metadata": {"fingerprint": "sha256:abc"},
    }
    store.write_composition_manifest("run1", manifest)
    assert store.read_composition_manifest("run1") == manifest
    read_manifest = store.read_composition_manifest("run1")
    assert read_manifest is not None
    read_manifest["metadata"] = {}
    assert store.read_composition_manifest("run1") == manifest
    wrapper_path = store.local_run_dir("run1") / "config" / "composition_manifest.json"
    wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
    assert set(wrapper) == {
        "schema_version",
        "run_id",
        "created_at",
        "composition_manifest",
    }
    assert wrapper["schema_version"] == 1
    assert wrapper["run_id"] == "run1"
    assert wrapper["composition_manifest"] == manifest
    store.write_recipe_manifest("run1", ({"name": "demo"},))
    assert store.read_recipe_manifest("run1") == ({"name": "demo"},)

    store.write_provenance_document("run1", "environment", {"python": "3.12"})
    assert store.read_provenance_document("run1", "environment") == {"python": "3.12"}


def test_local_run_stage_docs_and_logs(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    store.create_run("run1")

    stage_status = StageStatusRecord(
        run_id="run1",
        stage_name="stage",
        status=StageStatus.PENDING,
        attempt=1,
        updated_at="2020-01-01T00:00:00Z",
    )
    store.write_stage_status("run1", "stage", stage_status)
    assert store.read_stage_status("run1", "stage") == stage_status

    store.write_stage_inputs(
        "run1",
        "stage",
        {
            "inp": ArtifactRef(
                artifact_id="other/one",
                uri="file:///tmp/other/one.json",
                artifact_type="json",
                codec_key="json.v1",
            ),
        },
        attempt=1,
    )
    assert store.read_stage_inputs("run1", "stage")

    store.write_stage_outputs(
        "run1",
        "stage",
        {
            "out": ArtifactRef(
                artifact_id="stage/out",
                uri="file:///tmp/stage/out.json",
                artifact_type="json",
                codec_key="json.v1",
            ),
        },
        attempt=1,
    )
    assert store.read_stage_outputs("run1", "stage")

    store.write_stage_fingerprint("run1", "stage", {"x": 1}, attempt=1)
    assert store.read_stage_fingerprint("run1", "stage") == {"x": 1}

    store.write_stage_failure("run1", "stage", {"reason": "boom"}, attempt=1)
    assert store.read_stage_failure("run1", "stage") == {"reason": "boom"}

    store.write_stage_provenance("run1", "stage", {"tool": "x"}, attempt=1)
    assert store.read_stage_provenance("run1", "stage") == {"tool": "x"}

    store.write_stage_log("run1", "stage", "stdout", "line1\n")
    assert store.read_stage_log("run1", "stage", "stdout") == "line1\n"


def test_local_run_reads_and_writes_blocked_stage_status_only(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    store.create_run("run1")
    status = StageStatusRecord(
        run_id="run1",
        stage_name="blocked",
        status=StageStatus.BLOCKED,
        attempt=1,
        updated_at="2020-01-01T00:00:00Z",
        message="upstream failed",
        metadata={"blocked_by": ["stage"], "reason_code": "upstream_failed"},
    )

    store.write_stage_status("run1", "blocked", status)

    assert store.read_stage_status("run1", "blocked") == status
    stage_dir = store.local_stage_dir("run1", "blocked")
    assert sorted(path.name for path in stage_dir.iterdir()) == ["status.json"]


def test_local_run_rejects_corrupt_stage_plain_mapping(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    store.create_run("run1")
    atomic_write_json(
        store.local_stage_dir("run1", "stage") / "fingerprint.json",
        {
            "schema_version": 1,
            "run_id": "run1",
            "stage_name": "stage",
            "attempt": 1,
            "created_at": "2020-01-01T00:00:00Z",
            "fingerprint": ["not", "a", "mapping"],
        },
    )

    with pytest.raises(CorruptStoreDocumentError):
        store.read_stage_fingerprint("run1", "stage")


def test_local_run_rejects_non_mapping_composition_manifest_write(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    store.create_run("run1")

    with pytest.raises(UnsafeStorePathError, match="composition manifest"):
        store.write_composition_manifest("run1", ["not", "a", "mapping"])  # type: ignore[arg-type]


def test_local_run_validates_composition_manifest_wrapper(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    store.create_run("run1")
    path = store.local_run_dir("run1") / "config" / "composition_manifest.json"
    valid_timestamp = "2020-01-01T00:00:00Z"
    valid = {
        "schema_version": 1,
        "run_id": "run1",
        "created_at": valid_timestamp,
        "composition_manifest": {"source_artifacts": []},
    }
    cases = [
        {key: value for key, value in valid.items() if key != "composition_manifest"},
        {**valid, "unexpected": True},
        {**valid, "schema_version": 2},
        {**valid, "run_id": "other"},
        {**valid, "created_at": "2020-01-01 00:00:00"},
        {**valid, "composition_manifest": []},
    ]

    for payload in cases:
        atomic_write_json(path, payload)
        with pytest.raises(CorruptStoreDocumentError) as exc_info:
            store.read_composition_manifest("run1")
        assert str(path) in str(exc_info.value)


def test_local_run_rejects_corrupt_wrapper_fields_with_document_path(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    store.create_run("run1")
    run_dir = store.local_run_dir("run1")
    stage_dir = store.local_stage_dir("run1", "stage")
    valid_timestamp = "2020-01-01T00:00:00Z"
    cases: list[tuple[Path, dict[str, object], Callable[[], object]]] = [
        (
            run_dir / "run.json",
            {
                "schema_version": 1,
                "run_id": "run1",
                "created_at": valid_timestamp,
                "run_dir": "file:///tmp/run1",
            },
            lambda: store.read_run_document("run1"),
        ),
        (
            run_dir / "plan.json",
            {
                "schema_version": 1,
                "run_id": "run1",
                "updated_at": "2020-01-01 00:00:00",
                "plan": {},
            },
            lambda: store.read_plan("run1"),
        ),
        (
            run_dir / "artifacts.json",
            {
                "schema_version": True,
                "run_id": "run1",
                "updated_at": valid_timestamp,
                "artifacts": {},
            },
            lambda: store.read_artifact_index("run1"),
        ),
        (
            run_dir / "config" / "composition_manifest.json",
            {
                "schema_version": 1,
                "run_id": "run1",
                "created_at": valid_timestamp,
            },
            lambda: store.read_composition_manifest("run1"),
        ),
        (
            run_dir / "config" / "recipe_manifest.json",
            {
                "schema_version": 1,
                "run_id": "run1",
                "created_at": valid_timestamp,
            },
            lambda: store.read_recipe_manifest("run1"),
        ),
        (
            store.local_provenance_path("run1", "environment"),
            {
                "schema_version": 1,
                "run_id": "run1",
                "kind": "environment",
                "created_at": valid_timestamp,
                "provenance": [],
            },
            lambda: store.read_provenance_document("run1", "environment"),
        ),
        (
            stage_dir / "fingerprint.json",
            {
                "schema_version": 1,
                "run_id": "run1",
                "stage_name": "stage",
                "attempt": 1,
                "created_at": 123,
                "fingerprint": {},
            },
            lambda: store.read_stage_fingerprint("run1", "stage"),
        ),
        (
            stage_dir / "failure.json",
            {
                "schema_version": 1,
                "run_id": "run1",
                "stage_name": "stage",
                "attempt": 1,
                "created_at": valid_timestamp,
                "failure": {},
            },
            lambda: store.read_stage_failure("run1", "stage"),
        ),
    ]

    for path, payload, reader in cases:
        atomic_write_json(path, payload)
        with pytest.raises(CorruptStoreDocumentError) as exc_info:
            reader()
        assert str(path) in str(exc_info.value)


def test_local_run_rejects_corrupt_artifact_index_refs(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    store.create_run("run1")
    run_dir = store.local_run_dir("run1")
    path = run_dir / "artifacts.json"
    atomic_write_json(
        path,
        {
            "schema_version": 1,
            "run_id": "run1",
            "updated_at": "2020-01-01T00:00:00Z",
            "artifacts": {
                "stage.output": {
                    "artifact_id": "",
                    "uri": "file:///tmp/out.json",
                    "artifact_type": "json",
                },
            },
        },
    )

    with pytest.raises(CorruptStoreDocumentError) as exc_info:
        store.read_artifact_index("run1")
    assert str(path) in str(exc_info.value)


def test_local_run_wraps_unsafe_root_artifact_index_keys_as_corrupt(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    store.create_run("run1")
    run_dir = store.local_run_dir("run1")
    path = run_dir / "artifacts.json"
    atomic_write_json(
        path,
        {
            "schema_version": 1,
            "run_id": "run1",
            "updated_at": "2020-01-01T00:00:00Z",
            "artifacts": {"stage.bad/name": _artifact_ref().to_dict()},
        },
    )

    with pytest.raises(CorruptStoreDocumentError) as exc_info:
        store.read_artifact_index("run1")
    assert str(path) in str(exc_info.value)


def test_local_run_wraps_stage_artifact_index_failures_as_corrupt(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    store.create_run("run1")
    path = store.local_stage_dir("run1", "stage") / "outputs.json"
    wrapper = {
        "schema_version": 1,
        "run_id": "run1",
        "stage_name": "stage",
        "attempt": 1,
        "created_at": "2020-01-01T00:00:00Z",
    }

    atomic_write_json(
        path, {**wrapper, "outputs": {"bad/name": _artifact_ref().to_dict()}}
    )
    with pytest.raises(CorruptStoreDocumentError) as unsafe_key_exc:
        store.read_stage_outputs("run1", "stage")
    assert str(path) in str(unsafe_key_exc.value)

    atomic_write_json(
        path,
        {
            **wrapper,
            "outputs": {
                "out": {
                    "artifact_id": "",
                    "uri": "file:///tmp/stage/out.json",
                    "artifact_type": "json",
                },
            },
        },
    )
    with pytest.raises(CorruptStoreDocumentError) as bad_ref_exc:
        store.read_stage_outputs("run1", "stage")
    assert str(path) in str(bad_ref_exc.value)
