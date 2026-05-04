"""Unit tests for local run-store behavior."""

from collections.abc import Callable
from pathlib import Path

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline import RunStatus, StageStatus
from loom.pipeline.status import RunStatusRecord, StageStatusRecord
from loom.pipeline.stores import CorruptStoreDocumentError, LocalRunStore, atomic_write_json
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
    store.write_recipe_manifest("run1", ( {"name": "demo"}, ))
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


def test_local_run_rejects_corrupt_wrapper_fields_with_document_path(tmp_path: Path) -> None:
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


def test_local_run_wraps_unsafe_root_artifact_index_keys_as_corrupt(tmp_path: Path) -> None:
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


def test_local_run_wraps_stage_artifact_index_failures_as_corrupt(tmp_path: Path) -> None:
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

    atomic_write_json(path, {**wrapper, "outputs": {"bad/name": _artifact_ref().to_dict()}})
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
