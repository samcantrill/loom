"""Integration coverage for local artifact and run-store behavior."""

from pathlib import Path

from loom.artifacts import ArtifactRef
from loom.pipeline.status import RunStatusRecord
from loom.pipeline.status import RunStatus
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore


def test_local_stores_integration_roundtrip(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    run_store = LocalRunStore(root=root)
    run_store.create_run("run-1", metadata={"owner": "integration"})

    run_id = "run-1"
    artifact_root = run_store.local_artifact_root(run_id)
    artifact_store = LocalArtifactStore(root=artifact_root)

    json_ref = artifact_store.save(
        {"x": 1},
        stage_name="stage",
        name="data",
        artifact_type="json",
        codec_key="json.v1",
    )
    text_ref = artifact_store.save(
        "hello",
        stage_name="stage",
        name="report",
        artifact_type="text",
        codec_key="text.v1",
    )

    pre_written = tmp_path / "tmp_payload.bin"
    pre_written.write_text("already_here")
    registered = artifact_store.register(
        pre_written,
        stage_name="stage",
        name="pre",
        artifact_type="text",
        allow_external=True,
    )

    assert (artifact_root / "stage" / "data.json").exists()
    assert (artifact_root / "stage" / "report.txt").exists()
    assert artifact_store.exists(json_ref)

    run_store.write_artifact_index(run_id, {
        "stage.data": json_ref,
        "stage.report": text_ref,
        "stage.pre": registered,
    })
    read_index = run_store.read_artifact_index(run_id)
    assert isinstance(read_index["stage.data"], ArtifactRef)

    run_store.write_run_status(
        run_id,
        RunStatusRecord(
            run_id=run_id,
            status=RunStatus.SUCCEEDED,
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:00Z",
        ),
    )
    assert run_store.read_run_status(run_id)

    run_store.write_plan(run_id, {"stage": ["a", "b"]})
    assert run_store.read_plan(run_id) == {"stage": ["a", "b"]}

    run_store.write_config_snapshot(run_id, "resolved", "alpha: 1\n")
    assert run_store.read_config_snapshot(run_id, "resolved") == "alpha: 1\n"
    run_store.write_config_snapshot(run_id, "raw", "a: b\n")
    assert run_store.read_config_snapshot(run_id, "raw") == "a: b\n"

    run_store.write_recipe_manifest(run_id, ({"name": "demo"},))
    assert run_store.read_recipe_manifest(run_id) == ({"name": "demo"},)

    run_store.write_provenance_document(run_id, "git", {"commit": "abc"})
    assert run_store.read_provenance_document(run_id, "git") == {"commit": "abc"}

    run_store.write_stage_inputs(run_id, "stage", {"in": json_ref}, attempt=1)
    read_inputs = run_store.read_stage_inputs(run_id, "stage")
    assert read_inputs and set(read_inputs) == {"in"}

    run_store.write_stage_outputs(run_id, "stage", {"out": json_ref}, attempt=1)
    assert run_store.read_stage_outputs(run_id, "stage")

    run_store.write_stage_fingerprint(run_id, "stage", {"version": "1"}, attempt=1)
    run_store.write_stage_failure(run_id, "stage", {"message": "none"}, attempt=1)
    run_store.write_stage_provenance(run_id, "stage", {"tool": "loom"}, attempt=1)
    run_store.write_stage_log(run_id, "stage", "stderr", "oops\n")

    required_files = [
        run_store.local_run_dir(run_id) / "run.json",
        run_store.local_run_dir(run_id) / "config" / "raw.yaml",
        run_store.local_run_dir(run_id) / "config" / "recipe_manifest.json",
        run_store.local_run_dir(run_id) / "provenance" / "git.json",
        run_store.local_run_dir(run_id) / "stages" / "stage" / "inputs.json",
        run_store.local_run_dir(run_id) / "stages" / "stage" / "outputs.json",
        run_store.local_run_dir(run_id) / "stages" / "stage" / "fingerprint.json",
        run_store.local_run_dir(run_id) / "stages" / "stage" / "failure.json",
        run_store.local_run_dir(run_id) / "stages" / "stage" / "provenance.json",
        run_store.local_run_dir(run_id) / "stages" / "stage" / "logs" / "stderr.log",
        run_store.local_run_dir(run_id) / "plan.json",
        run_store.local_run_dir(run_id) / "artifacts.json",
        artifact_root / "stage",
        run_store.local_config_path(run_id, "raw"),
    ]

    for path in required_files:
        assert path.exists()
