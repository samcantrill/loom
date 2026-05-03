"""Unit tests for local run-store behavior."""

from pathlib import Path

from loom.artifacts import ArtifactRef
from loom.pipeline import RunStatus, StageStatus
from loom.pipeline.status import RunStatusRecord, StageStatusRecord
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore


def test_local_run_creation_writes_layout(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_dir = store.create_run("run1", metadata={"project": "demo"})

    assert run_dir.exists()
    assert (run_dir / "config").is_dir()
    assert (run_dir / "provenance").is_dir()
    assert (run_dir / "stages").is_dir()
    assert (run_dir / "artifacts").is_dir()
    assert (run_dir / "run.json").is_file()


def test_open_run_validates_required_run_metadata(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_dir = store.create_run("run1")
    assert store.open_run("run1") == run_dir


def test_local_run_metadata_optional_reads(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    store.create_run("run1", metadata={"a": 1})
    metadata = store.read_run_metadata("run1")
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

    plan_payload = {"stage": ["a", "b"]}
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
