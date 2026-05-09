"""Integration coverage for local artifact and run-store behavior."""

from pathlib import Path

from loom.artifacts import ArtifactRef
from loom.pipeline.events import EventScope, PipelineEvent
from loom.pipeline.execution import PreparedRunRecord
from loom.pipeline.status import (
    RunStatus,
    RunStatusRecord,
    StageStatus,
    StageStatusRecord,
)
from loom.pipeline.submitted import SubmittedOperationRecord, SubmittedOperationState
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore, path_to_run_uri


def test_local_stores_integration_roundtrip(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    run_store = LocalRunStore(root=root)
    run_uri = path_to_run_uri(root / "run-1")
    run_store.create_run(run_uri, metadata={"owner": "integration"})
    initial_freshness = run_store.read_run_freshness(run_uri)
    assert initial_freshness is not None

    artifact_root = run_store.local_artifact_root(run_uri)
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

    run_store.write_artifact_index(
        run_uri,
        {
            "stage.data": json_ref,
            "stage.report": text_ref,
            "stage.pre": registered,
        },
    )
    read_index = run_store.read_artifact_index(run_uri)
    assert isinstance(read_index["stage.data"], ArtifactRef)

    run_store.write_run_status(
        run_uri,
        RunStatusRecord(
            run_uri=run_uri,
            status=RunStatus.SUCCEEDED,
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:00Z",
        ),
    )
    assert run_store.read_run_status(run_uri)

    run_store.write_plan(run_uri, {"stage": ["a", "b"]})
    assert run_store.read_plan(run_uri) == {"stage": ["a", "b"]}

    prepared_run = PreparedRunRecord(
        schema_version=1,
        run_uri=run_uri,
        prepared_at="2020-01-01T00:00:00Z",
        executor_name="local",
        continuation_type="whole_run",
        plan={"plan_path": "plan.json", "plan_summary": {"stage_count": 1}},
        config={"composition_manifest_ref": "config/composition_manifest.json"},
        provenance={"command_ref": "provenance/command.json"},
        runtime={"document_ref": "runtime.json", "executor": "local"},
    )
    run_store.write_prepared_run(run_uri, prepared_run.to_dict())
    assert (
        PreparedRunRecord.from_dict(run_store.read_prepared_run(run_uri))
        == prepared_run
    )
    run_store.write_runtime_metadata(run_uri, {"executor": "local", "backend": "local"})
    assert run_store.read_runtime_metadata(run_uri) == {
        "executor": "local",
        "backend": "local",
    }
    run_store.write_submitted_operation(
        run_uri,
        SubmittedOperationRecord(
            run_uri=run_uri,
            submission_id="sub-1",
            backend="fake-slurm",
            mode="batch",
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:01Z",
            state=SubmittedOperationState.COMPLETED,
            manifest_relative_path="submitted/sub-1/manifest.json",
            summary_counts={"completed": 1},
        ),
    )
    assert run_store.latest_submitted_operation(run_uri)
    assert (
        run_store.local_generated_artifact_path(
            run_uri,
            "generated/submissions/p1/manifest.json",
        )
        == run_store.local_run_dir(run_uri)
        / "generated"
        / "submissions"
        / "p1"
        / "manifest.json"
    )

    first_event = run_store.append_event(
        run_uri,
        PipelineEvent(scope=EventScope.run(), event_type="run.created"),
    )
    second_event = run_store.append_event(
        run_uri,
        PipelineEvent(scope=EventScope.stage("stage"), event_type="stage.started"),
    )
    assert (first_event.sequence, second_event.sequence) == (1, 2)
    assert [record.event_type for record in run_store.read_events(run_uri)] == [
        "run.created",
        "stage.started",
    ]

    lock_record = run_store.acquire_run_lock(run_uri, owner={"workflow": "integration"})
    assert run_store.read_run_lock(run_uri) == lock_record
    assert (run_store.local_run_dir(run_uri) / "lock.json").exists()
    run_store.release_run_lock(run_uri, lock_record.token)
    assert run_store.read_run_lock(run_uri) is None

    run_store.write_config_snapshot(run_uri, "resolved", "alpha: 1\n")
    assert run_store.read_config_snapshot(run_uri, "resolved") == "alpha: 1\n"
    run_store.write_config_snapshot(run_uri, "raw", "a: b\n")
    assert run_store.read_config_snapshot(run_uri, "raw") == "a: b\n"

    run_store.write_composition_manifest(
        run_uri,
        {"source_artifacts": [{"kind": "config", "path": "base.yaml"}]},
    )
    assert run_store.read_composition_manifest(run_uri) == {
        "source_artifacts": [{"kind": "config", "path": "base.yaml"}]
    }
    run_store.write_recipe_manifest(run_uri, ({"name": "demo"},))
    assert run_store.read_recipe_manifest(run_uri) == ({"name": "demo"},)

    run_store.write_provenance_document(run_uri, "git", {"commit": "abc"})
    assert run_store.read_provenance_document(run_uri, "git") == {"commit": "abc"}

    run_store.write_stage_inputs(run_uri, "stage", {"in": json_ref}, attempt=1)
    read_inputs = run_store.read_stage_inputs(run_uri, "stage")
    assert read_inputs and set(read_inputs) == {"in"}

    run_store.write_stage_outputs(run_uri, "stage", {"out": json_ref}, attempt=1)
    assert run_store.read_stage_outputs(run_uri, "stage")

    run_store.write_stage_fingerprint(run_uri, "stage", {"version": "1"}, attempt=1)
    run_store.write_stage_failure(run_uri, "stage", {"message": "none"}, attempt=1)
    run_store.write_stage_worker_request(
        run_uri, "stage", {"executor": "local"}, attempt=1
    )
    run_store.write_stage_worker_result(run_uri, "stage", {"status": "ok"}, attempt=1)
    run_store.write_stage_provenance(run_uri, "stage", {"tool": "loom"}, attempt=1)
    run_store.write_stage_log(run_uri, "stage", "stderr", "oops\n")
    blocked_status = StageStatusRecord(
        run_uri=run_uri,
        stage_name="blocked",
        status=StageStatus.BLOCKED,
        attempt=1,
        updated_at="2020-01-01T00:00:00Z",
        message="upstream failed",
        metadata={"blocked_by": ["stage"], "reason_code": "upstream_failed"},
    )
    run_store.write_stage_status(run_uri, "blocked", blocked_status)
    assert run_store.read_stage_status(run_uri, "blocked") == blocked_status
    blocked_dir = run_store.local_stage_dir(run_uri, "blocked")
    assert sorted(path.name for path in blocked_dir.iterdir()) == ["status.json"]

    required_files = [
        run_store.local_run_dir(run_uri) / "run.json",
        run_store.local_run_freshness_path(run_uri),
        run_store.local_run_dir(run_uri) / "config" / "raw.yaml",
        run_store.local_run_dir(run_uri) / "config" / "composition_manifest.json",
        run_store.local_run_dir(run_uri) / "config" / "recipe_manifest.json",
        run_store.local_run_dir(run_uri) / "provenance" / "git.json",
        run_store.local_run_dir(run_uri) / "stages" / "stage" / "inputs.json",
        run_store.local_run_dir(run_uri) / "stages" / "stage" / "outputs.json",
        run_store.local_run_dir(run_uri) / "stages" / "stage" / "fingerprint.json",
        run_store.local_run_dir(run_uri) / "stages" / "stage" / "failure.json",
        run_store.local_run_dir(run_uri) / "stages" / "stage" / "worker_request.json",
        run_store.local_run_dir(run_uri) / "stages" / "stage" / "worker_result.json",
        run_store.local_run_dir(run_uri) / "stages" / "stage" / "provenance.json",
        run_store.local_run_dir(run_uri) / "stages" / "stage" / "logs" / "stderr.log",
        run_store.local_run_dir(run_uri) / "stages" / "blocked" / "status.json",
        run_store.local_run_dir(run_uri) / "plan.json",
        run_store.local_run_dir(run_uri) / "prepared_run.json",
        run_store.local_run_dir(run_uri) / "runtime.json",
        run_store.local_run_dir(run_uri) / "submitted_operations" / "sub-1.json",
        run_store.local_run_dir(run_uri) / "events.jsonl",
        run_store.local_run_dir(run_uri) / "artifacts.json",
        artifact_root / "stage",
        run_store.local_config_path(run_uri, "raw"),
    ]

    for path in required_files:
        assert path.exists()

    final_freshness = run_store.read_run_freshness(run_uri)
    assert final_freshness is not None
    assert final_freshness.token != initial_freshness.token
    assert final_freshness.revision > initial_freshness.revision
    assert final_freshness.reason == "stage_status"
