from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from loom.queue.errors import QueueServiceError
from loom.queue.slurm_ready_stage import SQLiteSlurmStageAssignments


def _shared_slurm_workspace(tmp_path):
    from dataclasses import fields, replace
    from tests.unit.loom.queue.test_remote_stage_execution import _shared_publication_workspace
    from loom.queue.slurm_ready_stage import SlurmBootstrapWorkspace, SlurmStageDelivery

    resident, profile, _launch, result = _shared_publication_workspace(tmp_path)
    request = resident.request()
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
