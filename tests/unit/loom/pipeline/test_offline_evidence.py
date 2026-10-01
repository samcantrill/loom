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


def test_explicit_export_is_revision_labelled_immutable_history(tmp_path: Path) -> None:
    from loom.pipeline.execution import create_authority_backed_serial_run_store
    from loom.pipeline.offline_evidence import write_offline_evidence_manifest
    from loom.pipeline.status import RunStatus
    from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore

    authority = SQLitePerRunAuthorityStore()
    local = LocalRunStore(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "export")
    store = create_authority_backed_serial_run_store(local.root, authority_store=authority)
    store.create_run(run_uri)
    authority.transition_run(run_uri, from_status=RunStatus.CREATED, to_status=RunStatus.RUNNING)
    revision = authority.snapshot(run_uri).revision
    manifest = write_offline_evidence_manifest(
        local, run_uri, authority_store=authority, generated_at="2026-10-01T00:00:00Z",
    )
    path = local.local_generated_artifact_path(run_uri, "offline-evidence/manifest.json")
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    assert manifest.run_status is not None
    assert manifest.run_status["status"] == "RUNNING"
    assert manifest.state_source["authoritative"] is False
    assert manifest.state_source["details"] == {
        "historical": True, "observed_at": "2026-10-01T00:00:00Z",
        "authority_revision": revision.to_dict(),
    }
    authority.transition_run(run_uri, from_status=RunStatus.RUNNING, to_status=RunStatus.SUCCEEDED)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert read_offline_evidence_manifest(path) == manifest
    assert not list(local.local_run_dir(run_uri).rglob("status.json"))


def test_export_records_unavailable_authority_without_stale_projection(tmp_path: Path) -> None:
    from loom.pipeline.offline_evidence import collect_offline_evidence_manifest
    from loom.pipeline.status import RunStatus, RunStatusRecord

    store = LocalRunStore(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "unavailable")
    store.create_run(run_uri)
    store.write_run_status(run_uri, RunStatusRecord(
        run_uri=run_uri, status=RunStatus.SUCCEEDED,
        created_at="2020-01-01T00:00:00Z", updated_at="2020-01-01T00:00:00Z",
    ))
    root = store.local_run_dir(run_uri)
    (root / ".loom").mkdir()
    before = {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in root.rglob("*") if path.is_file()}
    manifest = collect_offline_evidence_manifest(store, run_uri)
    assert manifest.run_status is None
    assert not manifest.complete
    assert "offline_evidence.authority_unavailable" in {item.code for item in manifest.diagnostics}
    assert {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in root.rglob("*") if path.is_file()} == before
