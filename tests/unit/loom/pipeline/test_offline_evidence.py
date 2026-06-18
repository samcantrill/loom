"""Unit tests for offline evidence manifests."""

from pathlib import Path

import pytest

from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.execution import create_offline_evidence_run_store
from loom.pipeline.offline_evidence import (
    OFFLINE_EVIDENCE_KIND,
    OfflineEvidenceError,
    OfflineEvidenceManifest,
    read_offline_evidence_manifest,
)
from loom.pipeline.status import RunStatus
from loom.pipeline.stores import path_to_run_uri
from tests.support.pipeline_execution_configs import local_execution_config


pytestmark = pytest.mark.unit


def test_offline_evidence_manifest_round_trips_after_offline_run(
    tmp_path: Path,
) -> None:
    store = create_offline_evidence_run_store(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "run1")

    result = PipelineRunner(run_store=store).run(
        RunRequest(config=local_execution_config(), run_uri=run_uri)
    )

    manifest_path = store.offline_evidence_manifest_path(run_uri)
    manifest = read_offline_evidence_manifest(manifest_path)
    assert result.status is RunStatus.SUCCEEDED
    assert manifest.kind == OFFLINE_EVIDENCE_KIND
    assert manifest.complete
    assert manifest.state_source["authoritative"] is False
    assert manifest.run_status is not None
    assert manifest.run_status["status"] == "SUCCEEDED"
    assert manifest.plan is not None
    assert manifest.plan["kind"] == "loom.execution_plan"
    assert [stage.stage_name for stage in manifest.stages] == ["build", "report"]
    assert [event["event_type"] for event in manifest.events][-1] == "run.completed"
    build = manifest.stages[0]
    assert build.resources is not None
    assert build.artifacts[0].payload is not None
    assert build.artifacts[0].payload.exists is True
    assert build.artifacts[0].payload.checksum is not None
    assert store.read_offline_evidence_manifest(run_uri) == manifest


def test_offline_evidence_manifest_marks_incomplete_local_state(
    tmp_path: Path,
) -> None:
    store = create_offline_evidence_run_store(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "incomplete")
    store.create_run(run_uri, metadata={})

    assert not store.offline_evidence_manifest_path(run_uri).exists()

    from loom.pipeline.offline_evidence import write_offline_evidence_manifest

    manifest = write_offline_evidence_manifest(store.local_store, run_uri)

    assert not manifest.complete
    assert {diagnostic.code for diagnostic in manifest.diagnostics} >= {
        "offline_evidence.run_status_missing",
        "offline_evidence.plan_missing",
        "offline_evidence.runtime_missing",
    }


def test_offline_evidence_manifest_rejects_wrong_kind(tmp_path: Path) -> None:
    store = create_offline_evidence_run_store(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "run1")
    PipelineRunner(run_store=store).run(
        RunRequest(config=local_execution_config(), run_uri=run_uri)
    )
    manifest = store.read_offline_evidence_manifest(run_uri)
    assert manifest is not None
    payload = manifest.to_dict()
    payload["kind"] = "wrong"

    with pytest.raises(OfflineEvidenceError, match="kind"):
        OfflineEvidenceManifest.from_dict(payload)
