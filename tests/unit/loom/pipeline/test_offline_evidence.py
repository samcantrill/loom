"""Unit tests for offline evidence manifests."""

from pathlib import Path

import pytest

from loom.pipeline.offline_evidence import (
    OFFLINE_EVIDENCE_KIND,
    OfflineEvidenceError,
    OfflineEvidenceManifest,
    read_offline_evidence_manifest,
)
from loom.pipeline.stores import LocalRunStore, path_to_run_uri
from tests.support.historical_offline_evidence import complete_manifest


pytestmark = pytest.mark.unit


def test_historical_offline_evidence_manifest_round_trips(
    tmp_path: Path,
) -> None:
    import json

    original = complete_manifest(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(original.to_dict()))
    manifest = read_offline_evidence_manifest(manifest_path)
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
    assert manifest == original


def test_offline_evidence_manifest_marks_incomplete_local_state(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "incomplete")
    store.create_run(run_uri, metadata={})

    assert not (store.local_run_dir(run_uri) / "offline-evidence.json").exists()

    from loom.pipeline.offline_evidence import write_offline_evidence_manifest

    manifest = write_offline_evidence_manifest(store, run_uri)

    assert not manifest.complete
    assert {diagnostic.code for diagnostic in manifest.diagnostics} >= {
        "offline_evidence.run_status_missing",
        "offline_evidence.plan_missing",
        "offline_evidence.runtime_missing",
    }


def test_offline_evidence_manifest_rejects_wrong_kind(tmp_path: Path) -> None:
    manifest = complete_manifest(tmp_path)
    payload = manifest.to_dict()
    payload["kind"] = "wrong"

    with pytest.raises(OfflineEvidenceError, match="kind"):
        OfflineEvidenceManifest.from_dict(payload)
