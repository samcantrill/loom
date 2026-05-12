"""Unit coverage for strict offline evidence import."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from itertools import count
from pathlib import Path
from typing import cast

import pytest

from loom.authority._repository import (
    AuthorityRepositoryError,
    initialize_authority_repository,
)
from loom.authority.offline_import import (
    OfflineImportError,
    OfflineImportRejectionKind,
    import_offline_evidence_manifest,
    validate_offline_import_manifest,
)
from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.execution import create_offline_evidence_run_store
from loom.pipeline.events import PipelineEventRecord
from loom.pipeline.offline_evidence import OfflineEvidenceManifest
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import path_to_run_uri
from loom.serialization import thaw_plain_data
from tests.support.pipeline_execution_configs import local_execution_config


pytestmark = pytest.mark.unit


def test_offline_import_accepts_complete_manifest_and_writes_authority_facts(
    tmp_path: Path,
) -> None:
    manifest = _complete_manifest(tmp_path)
    repository = initialize_authority_repository(
        tmp_path / "authority",
        service_generation="generation-1",
    )

    assert validate_offline_import_manifest(manifest) == ()

    result = import_offline_evidence_manifest(
        repository,
        manifest,
        imported_by="pytest",
        workspace_id="workspace-a",
    )

    snapshot = repository.open_run(manifest.run_uri)
    audit_events = repository.list_audit_events(manifest.run_uri)
    event_types = [event.event_type for event in audit_events]
    replay_events = [
        event
        for event in audit_events
        if event.event_type.startswith("offline_import.replay")
    ]
    _assert_replay_events_match_manifest(manifest, replay_events)

    assert result.run_uri == manifest.run_uri
    assert result.status == RunStatus.SUCCEEDED.value
    assert result.imported_stage_count == len(manifest.stages)
    assert result.imported_artifact_count == 2
    assert snapshot.status is RunStatus.SUCCEEDED
    assert [stage.status for stage in snapshot.stages] == [
        StageStatus.SUCCEEDED,
        StageStatus.SUCCEEDED,
    ]
    import_provenance = snapshot.metadata["authority_import"]
    assert isinstance(import_provenance, Mapping)
    assert import_provenance["source"] == "offline_evidence"
    assert import_provenance["workspace_id"] == "workspace-a"
    assert event_types[0] == "offline_import.accepted"
    assert len(replay_events) == len(manifest.events)
    assert replay_events[0].event_type == "offline_import.replay.run.created"
    assert replay_events[-1].event_type == "offline_import.replay.run.completed"
    assert "offline_import.replay.run.completed" in event_types


def _assert_replay_events_match_manifest(
    manifest: OfflineEvidenceManifest,
    replay_events: tuple[PipelineEventRecord, ...] | list[PipelineEventRecord],
) -> None:
    manifest_events = tuple(
        PipelineEventRecord.from_dict(event) for event in manifest.events
    )
    assert len(replay_events) == len(manifest_events)

    for manifest_event, replay_event in zip(
        manifest_events, cast(tuple[PipelineEventRecord, ...], tuple(replay_events))
    ):
        assert replay_event.event_type == f"offline_import.replay.{manifest_event.event_type}"
        assert replay_event.sequence == manifest_event.sequence + 1
        assert replay_event.scope == manifest_event.scope
        assert replay_event.timestamp == manifest_event.timestamp
        payload = cast(Mapping[str, object], replay_event.payload)
        offline_event = cast(Mapping[str, object], payload["offline_event"])
        assert PipelineEventRecord.from_dict(thaw_plain_data(offline_event)) == manifest_event
        assert offline_event["run_uri"] == manifest.run_uri
        assert offline_event["sequence"] == manifest_event.sequence
        assert offline_event["event_type"] == manifest_event.event_type
        assert offline_event["scope"] == manifest_event.scope.to_dict()
        assert offline_event["timestamp"] == manifest_event.timestamp


def test_offline_import_rejects_existing_run_identity(tmp_path: Path) -> None:
    manifest = _complete_manifest(tmp_path)
    repository = initialize_authority_repository(
        tmp_path / "authority",
        service_generation="generation-1",
    )
    import_offline_evidence_manifest(repository, manifest)

    with pytest.raises(OfflineImportError) as exc_info:
        import_offline_evidence_manifest(repository, manifest)

    assert exc_info.value.kind is OfflineImportRejectionKind.CONFLICT
    assert exc_info.value.diagnostics[0].code == "offline_import.repository_rejected"


def test_offline_import_validation_rejects_incomplete_manifest(tmp_path: Path) -> None:
    payload = _complete_manifest(tmp_path).to_dict()
    payload["manifest_status"] = "incomplete"
    manifest = OfflineEvidenceManifest.from_dict(payload)

    diagnostics = validate_offline_import_manifest(manifest)

    assert [diagnostic.code for diagnostic in diagnostics] == [
        "offline_import.incomplete_manifest"
    ]
    assert diagnostics[0].kind is OfflineImportRejectionKind.INCOMPLETE


def test_offline_import_validation_rejects_non_terminal_run_status(
    tmp_path: Path,
) -> None:
    payload = _complete_manifest(tmp_path).to_dict()
    run_status = cast(dict[str, object], payload["run_status"])
    run_status["status"] = RunStatus.RUNNING.value
    manifest = OfflineEvidenceManifest.from_dict(payload)

    diagnostics = validate_offline_import_manifest(manifest)

    assert "offline_import.run_status_non_terminal" in {
        diagnostic.code for diagnostic in diagnostics
    }


def test_offline_import_validation_rejects_artifact_output_mismatch(
    tmp_path: Path,
) -> None:
    payload = _complete_manifest(tmp_path).to_dict()
    stages = cast(list[dict[str, object]], payload["stages"])
    artifacts = cast(list[dict[str, object]], stages[0]["artifacts"])
    artifacts[0]["name"] = "missing-output"
    manifest = OfflineEvidenceManifest.from_dict(payload)

    diagnostics = validate_offline_import_manifest(manifest)

    assert "offline_import.artifact_without_output" in {
        diagnostic.code for diagnostic in diagnostics
    }


def test_offline_import_validation_rejects_event_run_uri_mismatch(
    tmp_path: Path,
) -> None:
    payload = _complete_manifest(tmp_path).to_dict()
    events = cast(list[dict[str, object]], payload["events"])
    events[0]["run_uri"] = "file:///runs/other"
    manifest = OfflineEvidenceManifest.from_dict(payload)

    diagnostics = validate_offline_import_manifest(manifest)

    assert "offline_import.event_run_uri_mismatch" in {
        diagnostic.code for diagnostic in diagnostics
    }


def test_offline_import_rolls_back_repository_transaction_on_mid_import_failure(
    tmp_path: Path,
) -> None:
    payload = _complete_manifest(tmp_path).to_dict()
    stages = cast(list[dict[str, object]], payload["stages"])
    outputs = cast(dict[str, object], stages[0]["outputs"])
    outputs["data"] = "not-an-artifact-ref"
    manifest = OfflineEvidenceManifest.from_dict(payload)
    repository = initialize_authority_repository(
        tmp_path / "authority",
        service_generation="generation-1",
    )

    with pytest.raises(AuthorityRepositoryError, match="offline evidence output"):
        repository.import_offline_evidence_manifest(manifest)

    with pytest.raises(AuthorityRepositoryError, match="unknown run"):
        repository.open_run(manifest.run_uri)


def _complete_manifest(tmp_path: Path, *, name: str = "offline-run") -> OfflineEvidenceManifest:
    run_store = create_offline_evidence_run_store(
        tmp_path / "offline-runs",
        owner_id="offline-test",
        workspace_id="workspace-a",
    )
    run_uri = path_to_run_uri(tmp_path / "offline-runs" / name)
    result = PipelineRunner(run_store=run_store, clock=_sequence_clock()).run(
        RunRequest(config=local_execution_config(), run_uri=run_uri)
    )
    assert result.status is RunStatus.SUCCEEDED
    manifest = run_store.read_offline_evidence_manifest(run_uri)
    assert manifest is not None
    return manifest


def _sequence_clock() -> Callable[[], str]:
    ticks = count(1)

    def clock() -> str:
        return f"2020-01-01T00:00:{next(ticks):02d}Z"

    return clock
