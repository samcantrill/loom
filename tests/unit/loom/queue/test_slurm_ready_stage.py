from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import json
from threading import Event
from typing import Any, cast
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from loom.queue.errors import QueueServiceError
from loom.queue.slurm_ready_stage import SQLiteSlurmStageAssignments


def test_repeated_delivery_reads_preserve_live_state_and_revalidate_changed_bytes(tmp_path, monkeypatch):
    from tests.unit.loom.queue.test_slurm_admission import ReservationFixture

    from loom.queue import slurm_ready_stage as module

    fixture = ReservationFixture(tmp_path)
    assignment, arguments = fixture.candidate("delivery-cache", 1)
    monkeypatch.setattr(module, "_retained_delivery_cache", module._RetainedDeliveryCache())
    assert [record.stage_work_id for record in fixture.work.ready_window()] == [assignment.stage_work_id]
    fixture.store.reserve(assignment, **arguments)
    assert fixture.work.ready_window() == ()
    assert fixture.store.read(assignment.assignment_id).delivery is arguments["delivery"]
    monkeypatch.setattr(module, "_retained_delivery_cache", module._RetainedDeliveryCache())
    original = module.SlurmStageDelivery.from_dict
    validations = []

    def validate(cls, value):
        validations.append(value["schema_version"])
        return original(value)

    monkeypatch.setattr(module.SlurmStageDelivery, "from_dict", classmethod(validate))
    first = fixture.store.read(assignment.assignment_id)
    fixture.store.advance(assignment.assignment_id, expected="reserved", next_state="bound")
    second = fixture.reopen().read(assignment.assignment_id)
    assert first.state == "reserved" and second.state == "bound"
    assert first.delivery is second.delivery
    assert len(validations) == 1
    with pytest.raises(TypeError):
        cast(dict[str, Any], second.delivery.resolved_runtime)["stage_id"] = "changed"
    with pytest.raises(TypeError):
        cast(dict[str, Any], second.delivery.fingerprint["payload"])["stage_name"] = "changed"

    # A changed persisted representation must not reuse an earlier validated
    # value for the same assignment, nor cache a failed validation.
    changed = second.delivery.to_dict()
    changed["schema_version"] = -1
    with sqlite3.connect(fixture.path) as conn:
        conn.execute("UPDATE slurm_stage_assignments SET delivery_json=? WHERE assignment_id=?",
                     (json.dumps(changed), assignment.assignment_id))
    for _ in range(2):
        with pytest.raises(QueueServiceError, match="schema is unsupported"):
            fixture.store.read(assignment.assignment_id)
    assert len(validations) == 3


def test_retained_delivery_cache_applies_total_byte_budget(tmp_path):
    from tests.unit.loom.queue.test_slurm_admission import ReservationFixture

    from loom.queue import slurm_ready_stage as module

    fixture = ReservationFixture(tmp_path)
    _, arguments = fixture.candidate("large-delivery", 0)
    delivery = arguments["delivery"]
    encoded = json.dumps(delivery.to_dict()) + " " * (1280 * 1024)
    size = len(encoded.encode("utf-8"))
    cache = module._RetainedDeliveryCache(max_encoded_bytes=size * 2 + 3)
    first = cache.read(encoded)
    second = cache.read(encoded + " ")
    assert first == second == delivery
    assert cache.read(encoded) is first
    cache.read(encoded + "  ")
    assert cache.read(encoded) is first
    assert cache.read(encoded + " ") is not second
    oversized = encoded + " " * (size + 4)
    assert cache.read(oversized) is not cache.read(oversized)


def test_concurrent_registration_reads_share_one_delivery_validation(tmp_path, monkeypatch):
    from tests.unit.loom.queue.test_slurm_admission import ReservationFixture

    from loom.queue import slurm_ready_stage as module

    fixture = ReservationFixture(tmp_path)
    _, arguments = fixture.candidate("concurrent-delivery-cache", 0)
    encoded = json.dumps(arguments["delivery"].to_dict()) + " " * (1280 * 1024)
    cache = module._RetainedDeliveryCache()
    started, waiting, finish = Event(), Event(), Event()
    decode = module._decode_retained_delivery
    calls = []

    class ObservedFuture(Future[module.SlurmStageDelivery]):
        def result(self, timeout: float | None = None) -> module.SlurmStageDelivery:
            waiting.set()
            return super().result(timeout)

    def validate(value):
        calls.append(value)
        started.set()
        assert finish.wait(5)
        return decode(value)

    monkeypatch.setattr(module, "Future", ObservedFuture)
    monkeypatch.setattr(module, "_decode_retained_delivery", validate)
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(cache.read, encoded)
        try:
            assert started.wait(5)
            replay = workers.submit(cache.read, encoded)
            assert waiting.wait(5)
        finally:
            finish.set()
        assert first.result() is replay.result()
    assert calls == [encoded]


@pytest.mark.parametrize("version", [3, 4, 5, 6])
def test_assignment_and_projection_share_one_version_on_initialize_and_reopen(tmp_path, version):
    from loom._sqlite_policy import SQLitePolicy
    from loom.queue._agent_slurm import SlurmSubmissionProjection

    path = tmp_path / "execution.sqlite"
    policy = SQLitePolicy("delete", "extra")
    projection = SlurmSubmissionProjection(path, _allow_initialize=True, sqlite_policy=policy, schema_version=version)
    owner = SQLiteSlurmStageAssignments(path, tmp_path / "transfers", sqlite_policy=policy, schema_version=version)
    owner._initialize()
    owner._open_existing()
    projection._open_existing()
    SlurmSubmissionProjection(path, _allow_initialize=True, sqlite_policy=policy, schema_version=version)._open_existing()
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone() == (version,)
        assert conn.execute("PRAGMA journal_mode").fetchone() == ("delete",)
    conn.close()
    other = 4 if version == 3 else 3
    with pytest.raises(QueueServiceError, match="migration"):
        SlurmSubmissionProjection(path, _allow_initialize=True, sqlite_policy=policy, schema_version=other)
    with pytest.raises(QueueServiceError, match="schema is unsupported"):
        SQLiteSlurmStageAssignments(path, tmp_path / "transfers", schema_version=other)._open_existing()
    projection._open_existing()
    owner._open_existing()


def test_strict_registration_replay_after_failed_sync(tmp_path, monkeypatch):
    import loom.pipeline.stores.atomic as atomic
    from loom.queue.slurm_ready_stage import SlurmBootstrapWorkspace

    workspace = SlurmBootstrapWorkspace(tmp_path / "compute", "assignment", durable_files="strict")
    sync = atomic._fsync_path_strict
    failed = False

    def fail_after_publish(path):
        nonlocal failed
        if (path / "registration.json").exists() and not failed:
            failed = True
            raise OSError("injected directory sync failure")
        sync(path)

    monkeypatch.setattr(atomic, "_fsync_path_strict", fail_after_publish)
    registration = {"assignment_id": "assignment", "delivery": {}}
    with pytest.raises(atomic.AtomicWriteError, match="sync failure"):
        workspace.persist_registration(registration)
    assert failed
    before = (workspace.root / "registration.json").read_bytes()
    workspace.persist_registration(registration)
    assert (workspace.root / "registration.json").read_bytes() == before


def _shared_slurm_workspace(tmp_path, *, assignment_id="assignment-1"):
    from dataclasses import fields, replace
    from tests.unit.loom.queue.test_remote_stage_execution import _shared_publication_workspace
    from loom.queue.slurm_ready_stage import SlurmBootstrapWorkspace, SlurmStageDelivery

    resident, profile, _launch, result = _shared_publication_workspace(tmp_path, assignment_id=assignment_id)
    request = resident.request()
    from loom.queue._remote_stage_execution import ResidentProfileDescriptor
    assert isinstance(request.profile, ResidentProfileDescriptor)
    values = {
        field.name: getattr(request, field.name)
        for field in fields(SlurmStageDelivery)
        if hasattr(request, field.name) and field.name != "schema_version"
    }
    delivery = SlurmStageDelivery(
        **values, profile_id="hpc-cpu",
        project_fingerprint=request.profile.project_fingerprint,
        environment_fingerprint=request.profile.environment_fingerprint,
        executor_fingerprint=request.profile.executor_fingerprint,
    )
    workspace = SlurmBootstrapWorkspace(tmp_path / "compute", request.assignment_id)
    workspace.persist_delivery(delivery)
    workspace.persist_execution_binding(
        agent_id="agent-1", fence="fence-1", profile=profile.launch_profile,
    )
    return workspace, profile, replace(result, run_uri=f"loom-slurm:{request.assignment_id}")


def test_shared_slurm_large_output_survives_relay_restart_and_lost_ack(tmp_path):
    from dataclasses import replace
    from loom.io.uris import uri_to_path
    from loom.queue._remote_stage_execution import MAX_TRANSFER_BYTES
    from loom.queue._slurm_result_transport import SharedSlurmResult
    from loom.queue import _shared_publication as publication

    workspace, profile, result = _shared_slurm_workspace(tmp_path)
    primary = uri_to_path(result.outputs["result"].uri)
    with primary.open("wb") as output:
        output.truncate(MAX_TRANSFER_BYTES + 1)
    result = replace(result, outputs={"result": replace(result.outputs["result"], checksum=None)})
    report = workspace.retain_result(result)
    assert report.output_kind == "shared"
    assert report.outputs[0].size_bytes == MAX_TRANSFER_BYTES + 1
    journal_root = tmp_path / "transport"
    journal_root.mkdir()
    storage = {"agent_root": str(journal_root), "compute_root": str(journal_root),
               "retention_bytes": 65 * 1024 * 1024}
    identity = {"assignment": {"assignment_id": workspace.root.name, "agent_id": "agent-1"},
                "fence": "fence-1", "incarnation": "bootstrap"}
    journal = SharedSlurmResult(storage, workspace.root.name)
    journal.reserve(identity["assignment"])
    journal.publish(identity, report, lambda *_: pytest.fail("shared payload was copied"))
    assert journal.read(identity) == (report, {})
    committed = []

    def relay(value):
        if value["result_operation"] == "report":
            assert value["report"] == report.to_dict()
            return {"accepted": True}
        assert value["result_operation"] == "commit"
        committed.append(publication.publish(
            workspace.delivery(), report, profile.shared_roots,
            agent_id="agent-1", fence="fence-1",
        ))
        if len(committed) == 1:
            raise OSError("commit acknowledgement lost")
        return {"acknowledged": True}

    with pytest.raises(OSError, match="acknowledgement"):
        journal.deliver(identity, relay)
    reopened = SharedSlurmResult(storage, workspace.root.name)
    assert reopened.deliver(identity, relay)
    assert committed[0] == committed[1]
    final = uri_to_path(committed[0]["result"].uri)
    assert final.stat().st_size == MAX_TRANSFER_BYTES + 1
    assert (final.parent / "values.bin").read_bytes() == b"companion-bytes"
    assert not journal.path.exists()
    assert workspace.retained_report() == report
    # The next Slurm stage consumes the same large publication by reference.
    from loom.queue._remote_stage_execution import _RemoteArtifact
    from loom.queue.slurm_ready_stage import SlurmBootstrapWorkspace
    from loom.queue.errors import QueueConflictError
    descriptor, _ = _RemoteArtifact.from_local_ref(
        transfer_id="checkpoint-input", logical_name="source", ref=committed[0]["result"],
    )
    successor = SlurmBootstrapWorkspace(tmp_path / "compute", "successor")
    successor.persist_delivery(replace(workspace.delivery(), assignment_id="successor", inputs=(descriptor,)))
    with pytest.raises(QueueConflictError, match="qualified roots"):
        successor.accept_inputs()
    successor.accept_inputs(shared_roots=profile.shared_roots)
    assert successor.worker_request(shared_roots=profile.shared_roots).inputs["source"].uri == final.as_uri()
    assert not (successor.root / "inputs").exists()
    with pytest.raises(QueueConflictError, match="not declared"):
        successor.stage_input_chunk(descriptor.transfer_id, 0, b"copied", final=True)


def test_shared_slurm_rejects_changed_closure_and_execution_binding(tmp_path):
    from loom.io.uris import uri_to_path
    from loom.queue.errors import QueueConflictError
    from loom.queue import _shared_publication as publication

    workspace, profile, result = _shared_slurm_workspace(tmp_path)
    report = workspace.retain_result(result)
    with pytest.raises(QueueConflictError, match="binding replay"):
        workspace.persist_execution_binding(
            agent_id="agent-1", fence="different-fence", profile=profile.launch_profile,
        )
    (uri_to_path(result.outputs["result"].uri).parent / "values.bin").write_bytes(b"changed")
    with pytest.raises(QueueConflictError):
        publication.publish(workspace.delivery(), report, profile.shared_roots,
                            agent_id="agent-1", fence="fence-1")


def test_assignment_store_requires_final_schema_identity(tmp_path: Path) -> None:
    path = tmp_path / "assignments.sqlite"
    store = SQLiteSlurmStageAssignments(path, tmp_path / "transfers")
    store._initialize()

    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        conn.execute("PRAGMA user_version = 2")

    with pytest.raises(QueueServiceError, match="schema is unsupported"):
        store._open_existing()


_RETIRED_ASSIGNMENT_COLUMNS = (
    "start_consumed",
    "agent_sequence",
    "agent_evidence_json",
    "agent_evidence_accepted_at",
)


def _storage_snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def test_fresh_assignment_store_contains_current_agent_evidence(tmp_path: Path) -> None:
    path = tmp_path / "assignments.sqlite"
    store = SQLiteSlurmStageAssignments(path, tmp_path / "transfers")
    store._initialize()
    with sqlite3.connect(path) as conn:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(slurm_stage_assignments)")
        }
        assert set(_RETIRED_ASSIGNMENT_COLUMNS) <= columns
        assert conn.execute("PRAGMA user_version").fetchone() == (3,)
    conn.close()
    before = _storage_snapshot(tmp_path)
    SQLiteSlurmStageAssignments(
        path, tmp_path / "transfers", _allow_initialize=False
    )._open_existing()
    store._initialize()
    assert _storage_snapshot(tmp_path) == before


@pytest.mark.parametrize("shape", ["native_only", "old_version", "missing_outputs"])
@pytest.mark.parametrize("entry", ["_open_existing", "_initialize"])
def test_retired_assignment_storage_refuses_before_mutation(
    tmp_path: Path, shape: str, entry: str
) -> None:
    path = tmp_path / "assignments.sqlite"
    store = SQLiteSlurmStageAssignments(path, tmp_path / "transfers")
    store._initialize()
    with sqlite3.connect(path) as conn:
        if shape == "native_only":
            # The empty schema-3 layout emitted before agent-owned Slurm (#312).
            for column in _RETIRED_ASSIGNMENT_COLUMNS:
                conn.execute(
                    f"ALTER TABLE slurm_stage_assignments DROP COLUMN {column}"
                )
        elif shape == "old_version":
            conn.execute("PRAGMA user_version = 2")
        else:
            conn.execute("DROP TABLE slurm_stage_outputs")
    conn.close()
    before = _storage_snapshot(tmp_path)
    with pytest.raises(QueueServiceError, match="schema is unsupported"):
        getattr(store, entry)()
    assert _storage_snapshot(tmp_path) == before


@pytest.mark.parametrize("retired", [False, True])
def test_interrupted_assignment_write_recovers_only_current_storage(
    tmp_path: Path, retired: bool
) -> None:
    path = tmp_path / "assignments.sqlite"
    store = SQLiteSlurmStageAssignments(path, tmp_path / "transfers")
    store._initialize()
    if retired:
        with sqlite3.connect(path) as conn:
            for column in _RETIRED_ASSIGNMENT_COLUMNS:
                conn.execute(
                    f"ALTER TABLE slurm_stage_assignments DROP COLUMN {column}"
                )
        conn.close()
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import os, sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
conn.execute("PRAGMA cache_size = 1")
conn.execute("BEGIN IMMEDIATE")
conn.executemany(
    "INSERT INTO slurm_stage_outputs VALUES (?, ?, ?, ?, ?)",
    (("assignment", str(i), "x" * 1000, 0, 0) for i in range(1000)),
)
os._exit(0)
""",
            str(path),
        ],
        check=True,
    )
    assert Path(str(path) + "-journal").is_file()
    before = _storage_snapshot(tmp_path)
    if retired:
        with pytest.raises(QueueServiceError, match="schema is unsupported"):
            store._initialize()
        assert _storage_snapshot(tmp_path) == before
    else:
        store._open_existing()
        assert _storage_snapshot(tmp_path) == before
        store._initialize()
        with sqlite3.connect(path) as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM slurm_stage_outputs"
            ).fetchone() == (0,)
        conn.close()


def test_native_preparation_framing_uses_existing_slurm_chunk_identity(tmp_path):
    import hashlib
    from tests.unit.loom.queue.test_remote_stage_execution import _preparation_output
    from loom.queue.slurm_ready_stage import SlurmBootstrapWorkspace
    from loom.queue._remote_stage_execution import (
        TRANSFER_CHUNK_BYTES,
        _atomic_regular_file,
    )

    _logical, original, _companion, data, item = _preparation_output(tmp_path)
    workspace = SlurmBootstrapWorkspace(tmp_path / "compute", "native-pair")
    wrapper = workspace.root / "retained-outputs/report"
    _atomic_regular_file(wrapper, data)
    transfer_id = (
        "output-"
        + hashlib.sha256(
            (workspace.root.name + "\0report\0" + item.digest).encode()
        ).hexdigest()
    )
    assert "sha256:" + item.digest != original.checksum
    chunks, offset = [], 0
    while True:
        chunk, final = workspace.output_chunk(transfer_id, offset)
        assert len(chunk) <= TRANSFER_CHUNK_BYTES
        assert workspace.output_chunk(transfer_id, offset) == (chunk, final)
        chunks.append(chunk)
        offset += len(chunk)
        if final:
            break
    assert b"".join(chunks) == data
    assert offset == item.size_bytes
    from loom.queue.errors import QueueConflictError

    with pytest.raises(QueueConflictError):
        item.local_ref(wrapper)
    wrapper.write_bytes(data[:-1])
    with pytest.raises(QueueConflictError, match="unavailable"):
        workspace.output_chunk(transfer_id, 0)


def test_pending_effect_upgrade_keeps_existing_gpu_reservations(tmp_path):
    from tests.unit.loom.queue.test_slurm_admission import ReservationFixture
    from loom.queue.slurm_ready_stage import _upgrade_pending_effects_schema

    fixture = ReservationFixture(tmp_path)
    assignment, arguments = fixture.candidate("pending-upgrade", 2)
    fixture.store.reserve(assignment, **arguments)
    with sqlite3.connect(fixture.path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        _upgrade_pending_effects_schema(conn)
        assert conn.execute(
            "SELECT requested_gpu_count, publication_requested_at, compute_released_at "
            "FROM slurm_stage_assignments WHERE assignment_id=?", (assignment.assignment_id,),
        ).fetchone() == (2, None, None)
    reopened = SQLiteSlurmStageAssignments(
        fixture.path, tmp_path / "transfer", schema_version=5,
    )
    assert reopened.reserved_gpu_count() == 2
    assert reopened.read(assignment.assignment_id).state == "reserved"


def _granted_fixture(root, *, version):
    import base64
    import hashlib
    from tests.unit.loom.queue.test_slurm_admission import ReservationFixture

    fixture = ReservationFixture(root, schema_version=version)
    assignment, arguments = fixture.candidate("start-replay", 0)
    store = fixture.store
    store.reserve(assignment, **arguments)
    store.advance(assignment.assignment_id, expected="reserved", next_state="bound")
    store.mark_submission_eligible(
        assignment.assignment_id, operation_id=assignment.operation_id,
        request_digest=assignment.request_digest, profile_id=assignment.profile_id,
        profile_descriptor=assignment.profile_descriptor,
        verifier=hashlib.sha256(b"capability").hexdigest(),
    )
    store.record_submission(assignment.assignment_id, state="accepted", job_id="123", cluster="site")
    store.register_bootstrap(
        assignment.operation_id, request_digest=assignment.request_digest,
        job_id="123", cluster="site", incarnation="bootstrap",
        capability=base64.b64encode(b"capability").decode(),
    )
    assert store.mark_input_ready(assignment.assignment_id, "bootstrap")
    store.mark_granted(assignment.assignment_id, "bootstrap", "fence")
    return fixture, assignment.assignment_id


def test_start_permit_exact_replay_survives_reopen_and_racing_other_invocation(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    fixture, assignment = _granted_fixture(tmp_path, version=6)
    barrier = Barrier(2)
    def start(request_id):
        store = fixture.reopen()
        barrier.wait(timeout=5)
        return request_id, store.consume_start(assignment, request_id=request_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = dict(pool.map(start, ("process-a", "process-b")))
    assert sorted(results.values()) == [False, True]
    winner = next(key for key, accepted in results.items() if accepted)
    reopened = fixture.reopen()
    assert reopened.consume_start(assignment, request_id=winner)
    assert not reopened.consume_start(assignment, request_id="restarted-process")
    assert not reopened.consume_start(assignment)  # Old caller cannot adopt it.
    assert reopened.read(assignment).start_request_id == winner


def test_migrated_consumed_legacy_start_cannot_be_adopted(tmp_path):
    from loom.queue.slurm_ready_stage import _upgrade_start_request_schema

    fixture, assignment = _granted_fixture(tmp_path, version=5)
    assert fixture.store.consume_start(assignment)
    with sqlite3.connect(fixture.path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        _upgrade_start_request_schema(conn)
    fixture.schema_version = 6
    reopened = fixture.reopen()
    assert reopened.read(assignment).start_request_id is None
    assert not reopened.consume_start(assignment, request_id="new-process")
    assert not reopened.consume_start(assignment)
