"""Unit tests for lifecycle status helpers."""

from pathlib import Path

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline import PipelineSpec
from loom.pipeline.execution.errors import PlanExecutionError
from loom.pipeline.execution.lifecycle import (
    bind_stage_inputs,
    write_stage_artifact_index_refs,
    write_stage_blocked,
)
from loom.pipeline.planning import plan_pipeline
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore, path_to_run_uri


def _run_uri(tmp_path: Path) -> str:
    return path_to_run_uri(tmp_path / "runs" / "run1")


def _ref(stage: str = "build", output: str = "data") -> ArtifactRef:
    return ArtifactRef(
        artifact_id=f"{stage}/{output}",
        uri=f"file:///tmp/{stage}/{output}.json",
        artifact_type="json",
        codec_key="json.v1",
    )


def _two_stage_spec() -> PipelineSpec:
    return PipelineSpec.from_config(
        {
            "stages": [
                {
                    "name": "build",
                    "factory": {
                        "_target_": "tests.support.pipeline_execution_stages.JsonProducerStage"
                    },
                    "outputs": {"data": {"artifact_type": "json"}},
                },
                {
                    "name": "report",
                    "factory": {
                        "_target_": "tests.support.pipeline_execution_stages.TextConsumerStage"
                    },
                    "inputs": {"data": "build.data"},
                    "outputs": {"text": {"artifact_type": "text"}},
                },
            ]
        }
    )


def test_write_stage_blocked_writes_status_only(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)

    record = write_stage_blocked(
        store,
        run_uri=run_uri,
        stage_name="downstream",
        attempt=1,
        blocked_at="2020-01-01T00:00:00Z",
        message="upstream failed",
        blocked_by=["upstream"],
        reason_code="upstream_failed",
        metadata={"reason_details": {"exit_code": 2}},
    )

    assert record.status is StageStatus.BLOCKED
    assert record.started_at is None
    assert record.finished_at is None
    assert record.owner == {}
    assert record.metadata == {
        "blocked_by": ["upstream"],
        "reason_code": "upstream_failed",
        "reason_details": {"exit_code": 2},
    }
    assert store.read_stage_status(run_uri, "downstream") == record

    stage_dir = store.local_stage_dir(run_uri, "downstream")
    assert sorted(path.name for path in stage_dir.iterdir()) == ["status.json"]
    assert store.read_stage_inputs(run_uri, "downstream") is None
    assert store.read_stage_outputs(run_uri, "downstream") is None
    assert store.read_stage_fingerprint(run_uri, "downstream") is None
    assert store.read_stage_failure(run_uri, "downstream") is None
    assert store.read_stage_provenance(run_uri, "downstream") is None
    assert not (stage_dir / "logs").exists()
    assert sorted(path.name for path in stage_dir.iterdir()) == ["status.json"]


def test_write_stage_blocked_requires_message_and_reason_code_when_present(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)

    with pytest.raises(ValueError, match="message"):
        write_stage_blocked(
            store,
            run_uri=run_uri,
            stage_name="downstream",
            attempt=1,
            blocked_at="2020-01-01T00:00:00Z",
            message="",
        )

    with pytest.raises(ValueError, match="reason_code"):
        write_stage_blocked(
            store,
            run_uri=run_uri,
            stage_name="downstream",
            attempt=1,
            blocked_at="2020-01-01T00:00:00Z",
            message="blocked",
            reason_code="",
        )


def test_bind_stage_inputs_uses_pending_outputs_without_status_side_effects(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    spec = _two_stage_spec()
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=store,
        artifact_store=LocalArtifactStore(store.local_artifact_root(run_uri)),
        persist=True,
    )
    report_plan = plan.ordered_stage_plans[1]

    inputs = bind_stage_inputs(
        stage=spec.get_stage("report"),
        stage_plan=report_plan,
        produced_outputs={"build": {"data": _ref()}},
    )

    assert inputs == {"data": _ref()}
    assert store.read_stage_status(run_uri, "report") is None
    with pytest.raises(PlanExecutionError, match="Cannot bind input"):
        bind_stage_inputs(
            stage=spec.get_stage("report"),
            stage_plan=report_plan,
            produced_outputs={},
        )


def test_write_stage_artifact_index_refs_preserves_merge_semantics(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    existing = _ref("old", "data")
    store.write_artifact_index(run_uri, {"build.data": existing})

    write_stage_artifact_index_refs(
        store,
        run_uri=run_uri,
        stage_name="report",
        outputs={"text": _ref("report", "text")},
        replace=False,
    )

    assert store.read_artifact_index(run_uri) == {
        "build.data": existing,
        "report.text": _ref("report", "text"),
    }
