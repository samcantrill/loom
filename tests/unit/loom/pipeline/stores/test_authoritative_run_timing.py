"""Durable timing through lifecycle, migration, and portable evidence boundaries."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
import json
import pickle
import sqlite3

import pytest

from loom.authority._repository import AuthorityRepository
from loom.pipeline.events import EventScope, PipelineEvent
from loom.pipeline.offline_evidence import collect_offline_evidence_manifest
from loom.pipeline.status import RunStatus
from loom.pipeline.stores import LocalRunStore, path_to_run_uri
from loom.pipeline.stores.authority import (
    CancellationEpochRequest,
    CoordinatorAdmissionRequest,
    PreparedAttemptRequest,
)
from loom.pipeline.stores.read_models import AuthoritativeRunSnapshot
from loom.pipeline.stores.sqlite_authority import (
    SQLitePerRunAuthorityStore,
    _authority_database_path,
)
from loom.pipeline.transition_policy import TransitionIntent
from tests.support.historical_offline_evidence import complete_manifest

pytestmark = pytest.mark.unit


@dataclass
class Clock:
    value: str = "2020-01-01T00:00:00Z"

    def __call__(self):
        return self.value


@pytest.fixture(params=["sqlite", "service"])
def authority(request, tmp_path):
    clock = Clock()
    uri = path_to_run_uri(tmp_path / "runs" / "timing")
    if request.param == "sqlite":
        store = SQLitePerRunAuthorityStore(clock=clock)
        database = _authority_database_path(uri)
    else:
        store = AuthorityRepository(tmp_path / "authority", clock=clock)
        store.initialize(service_generation="timing")
        database = store.database_path
    return store, clock, uri, database


def _admit(store, uri, **kwargs):
    if isinstance(store, SQLitePerRunAuthorityStore):
        return store.create_run(uri, **kwargs)
    return store.admit_run(uri, **kwargs)


def test_cancel_before_start_and_audit_revision_preserve_timing(authority):
    store, clock, uri, _ = authority
    _admit(store, uri)
    store.bind_coordinator_admission(
        uri, CoordinatorAdmissionRequest("admit", "coordinator", uri, "intent")
    )
    request = CancellationEpochRequest("cancel", "coordinator", uri, ("work",))
    store.install_cancellation_epoch(uri, request)
    clock.value = "2020-01-01T00:00:03Z"
    store.finalize_cancellation(uri, request)
    cancelled = store.open_run(uri)
    assert cancelled.started_at is None
    assert cancelled.started_at_known is True
    assert cancelled.finished_at == clock.value

    clock.value = "2020-01-01T00:00:05Z"
    store.append_audit_event(
        uri,
        PipelineEvent(
            scope=EventScope.run(), event_type="inspection.recorded", payload={}
        ),
    )
    store.finalize_cancellation(uri, request)
    later = store.open_run(uri)
    assert later.revision != cancelled.revision
    assert later.finished_at == cancelled.finished_at
    assert later.started_at is None


def test_managed_start_is_recorded_once_at_confirmation(authority):
    store, clock, uri, _ = authority
    revision = _admit(store, uri, status=RunStatus.PLANNED)
    prepared = store.ensure_prepared_attempt(
        uri,
        PreparedAttemptRequest(
            operation_id="prepare",
            request_digest="digest",
            admission_id="admission",
            stage_name="work",
            readiness_generation="generation",
            expected_revision=revision,
            expected_stage_status=None,
            expected_attempt_id=None,
            next_attempt=1,
            owner_id="coordinator",
            plan_fingerprint="plan",
            bound_inputs={},
            upstream_commits={},
        ),
    )
    store.bind_prepared_attempt(
        uri, assignment_id="assignment", attempt_id=prepared.attempt.attempt_id
    )
    fence = store.grant_prepared_attempt(
        uri, assignment_id="assignment", attempt_id=prepared.attempt.attempt_id
    )
    assert store.open_run(uri).started_at is None
    clock.value = "2020-01-01T00:00:03Z"
    store.confirm_execution_started(uri, fence=fence)
    started = store.open_run(uri)
    assert started.status is RunStatus.RUNNING
    assert started.started_at == clock.value
    assert started.finished_at is None
    clock.value = "2020-01-01T00:00:05Z"
    store.confirm_execution_started(uri, fence=fence)
    assert store.open_run(uri).started_at == started.started_at


def test_initial_running_admission_and_snapshot_round_trip(authority):
    store, clock, uri, _ = authority
    _admit(store, uri, status=RunStatus.RUNNING)
    snapshot = store.open_run(uri)
    assert snapshot.started_at == clock.value
    assert snapshot.started_at_known is True
    assert snapshot.finished_at is None
    assert (
        AuthoritativeRunSnapshot.from_dict(json.loads(json.dumps(snapshot.to_dict())))
        == snapshot
    )
    assert pickle.loads(pickle.dumps(snapshot)) == snapshot
    legacy = snapshot.to_dict()
    for key in ("started_at", "finished_at", "started_at_known"):
        del legacy[key]
    historical = AuthoritativeRunSnapshot.from_dict(legacy)
    assert historical.started_at is None
    assert historical.started_at_known is False


def test_interrupted_run_remains_unfinished_and_retains_first_start(authority):
    store, clock, uri, _ = authority
    _admit(store, uri, status=RunStatus.RUNNING)
    start = clock.value
    clock.value = "2020-01-01T00:00:03Z"
    store.transition_run(
        uri, from_status=RunStatus.RUNNING, to_status=RunStatus.INTERRUPTED
    )
    interrupted = store.open_run(uri)
    assert interrupted.started_at == start
    assert interrupted.finished_at is None
    clock.value = "2020-01-01T00:00:05Z"
    store.transition_run(
        uri,
        from_status=RunStatus.INTERRUPTED,
        to_status=RunStatus.RUNNING,
        intent=TransitionIntent.RESUME,
    )
    assert store.open_run(uri).started_at == start


def test_legacy_unknown_start_survives_read_only_admission_and_retry(authority):
    store, clock, uri, database = authority
    _admit(store, uri, status=RunStatus.FAILED)
    local = isinstance(store, SQLitePerRunAuthorityStore)
    table, metadata, version = (
        ("run_state", "metadata", 10)
        if local
        else ("authority_runs", "repository_metadata", 11)
    )
    # Construct the real preceding schema, including its absent timing columns.
    with sqlite3.connect(database) as conn:
        for column in ("started_at", "finished_at", "started_at_known"):
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        conn.execute(
            f"UPDATE {metadata} SET value = ? WHERE key = 'schema_version'",
            (str(version),),
        )
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    if local:
        before = {
            p.name: (p.read_bytes(), p.stat().st_mtime_ns)
            for p in database.parent.iterdir()
            if p.is_file()
        }
        historical = SQLitePerRunAuthorityStore(uri, read_only=True).open_run(uri)
        assert historical.started_at_known is False
        assert historical.started_at is None
        assert historical.finished_at is None
        after = {
            p.name: (p.read_bytes(), p.stat().st_mtime_ns)
            for p in database.parent.iterdir()
            if p.is_file()
        }
        assert after == before
    else:
        store.initialize(service_generation="timing")
    historical = store.open_run(uri)
    assert historical.started_at_known is False
    assert historical.started_at is None
    assert historical.finished_at is None
    clock.value = "2020-01-01T00:00:05Z"
    store.transition_run(
        uri,
        from_status=RunStatus.FAILED,
        to_status=RunStatus.PLANNED,
        intent=TransitionIntent.RESUME,
    )
    clock.value = "2020-01-01T00:00:06Z"
    store.transition_run(
        uri, from_status=RunStatus.PLANNED, to_status=RunStatus.RUNNING
    )
    resumed = store.open_run(uri)
    assert resumed.started_at is None
    assert resumed.started_at_known is False
    assert resumed.finished_at is None
    clock.value = "2020-01-01T00:00:07Z"
    store.transition_run(
        uri, from_status=RunStatus.RUNNING, to_status=RunStatus.SUCCEEDED
    )
    assert store.open_run(uri).finished_at == clock.value


def test_offline_export_preserves_authoritative_timing(tmp_path):
    clock = Clock()
    authority = SQLitePerRunAuthorityStore(clock=clock)
    local = LocalRunStore(tmp_path / "runs")
    uri = path_to_run_uri(tmp_path / "runs" / "timing")
    local.create_run(uri)
    authority.create_run(uri, status=RunStatus.RUNNING)
    start = clock.value
    clock.value = "2020-01-01T00:00:04Z"
    authority.transition_run(
        uri, from_status=RunStatus.RUNNING, to_status=RunStatus.SUCCEEDED
    )
    evidence = collect_offline_evidence_manifest(local, uri, authority_store=authority)
    assert evidence.run_status is not None
    assert evidence.run_status["started_at"] == start
    assert evidence.run_status["finished_at"] == clock.value
    details = evidence.state_source["details"]
    assert isinstance(details, Mapping)
    assert details["run_timing"] == {"started_at_known": True}


def test_catalog_scan_projects_retained_timing_after_later_audit(tmp_path):
    from loom.runs._scan import scan_current_collection

    clock = Clock()
    authority = SQLitePerRunAuthorityStore(clock=clock)
    collection = tmp_path / "runs"
    local = LocalRunStore(collection)
    uri = path_to_run_uri(collection / "timing")
    local.create_run(uri)
    authority.create_run(uri, status=RunStatus.PLANNED)
    planned = scan_current_collection(collection).summaries[0]
    assert planned.started_at is None
    assert planned.finished_at is None
    clock.value = "2020-01-01T00:00:01Z"
    authority.transition_run(uri, from_status=RunStatus.PLANNED, to_status=RunStatus.RUNNING)
    clock.value = "2020-01-01T00:00:04Z"
    authority.transition_run(uri, from_status=RunStatus.RUNNING, to_status=RunStatus.SUCCEEDED)
    clock.value = "2020-01-01T00:00:08Z"
    authority.append_audit_event(uri, PipelineEvent(
        scope=EventScope.run(), event_type="inspection.recorded", payload={}
    ))
    completed = scan_current_collection(collection).summaries[0]
    assert completed.started_at == "2020-01-01T00:00:01Z"
    assert completed.finished_at == "2020-01-01T00:00:04Z"


@pytest.mark.parametrize("start_known", [True, False, None])
def test_offline_import_retains_only_established_timing(tmp_path, start_known):
    manifest = complete_manifest(tmp_path)
    assert manifest.run_status is not None
    status = dict(manifest.run_status)
    status.update(started_at="2020-01-01T00:00:01Z", finished_at="2020-01-01T00:00:04Z")
    source = dict(manifest.state_source)
    if start_known is not None:
        source["details"] = {"run_timing": {"started_at_known": start_known}}
        if not start_known:
            # A migrated run can finish a retry while its first start is unknown.
            status["started_at"] = None
    manifest = replace(manifest, run_status=status, state_source=source)
    repository = AuthorityRepository(tmp_path / "authority")
    repository.initialize(service_generation="timing")
    snapshot = repository.import_offline_evidence_manifest(manifest)
    assert snapshot.started_at_known is bool(start_known)
    assert snapshot.started_at == (status["started_at"] if start_known else None)
    assert snapshot.finished_at == (status["finished_at"] if start_known is not None else None)
