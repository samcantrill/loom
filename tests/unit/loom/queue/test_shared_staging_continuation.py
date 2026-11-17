"""Released output assembly retains payload inodes across native attempts."""

from dataclasses import replace
import errno
import json
from pathlib import Path
import shutil

import pytest

from loom.pipeline.stores.shared_artifacts import RECEIPT, encoded
from loom.queue import _shared_publication as publication
from loom.queue import _shared_recovery as recovery
from loom.queue import _shared_staging_continuation as continuation
from loom.queue.errors import QueueConflictError
from loom.serialization import thaw_plain_data
from tests.unit.loom.queue.test_shared_recovery import _retention_database, _workspace, _write


def _guard(workspace):
    def require():
        if workspace.state() != "STARTED":
            raise QueueConflictError("current native assignment is no longer live")
        _, owner = publication.workspace_facts(workspace)
        assert owner["assignment_id"] == workspace.assignment_id
        assert owner["fence"] == "fence-1"
        return owner
    return require


def _retain(tmp_path, workspace, profile):
    _write(workspace)
    request = workspace.request()
    with _retention_database(tmp_path / "retention.sqlite") as connection:
        row = {"provider_release_proof_json": "positive-provider-release", "fence": "fence-1"}
        recovery.retain_released(connection, row, request, profile.shared_roots, agent_id="agent-1")
        reference = json.loads(connection.execute(
            "SELECT result_json FROM agent_receipts WHERE operation='seal' AND idempotency_key=?",
            (request.assignment_id,),
        ).fetchone()[0])
        connection.execute("INSERT INTO remote_assignments VALUES (?,?,?,?,?,?,?,?,?,?)", (
            request.assignment_id, "file:///fixture", request.stage_name, request.attempt,
            request.attempt_id, "RELEASED", row["provider_release_proof_json"],
            json.dumps({"status": "FAILED"}), "fence-1", 1,
        ))
        connection.execute("INSERT INTO agent_deliveries VALUES (?,?)", (
            request.assignment_id, encoded(request.to_dict()).decode(),
        ))
    return reference


def _staging(workspace):
    parent = publication.worker_artifact_root(workspace)
    assert parent is not None
    return parent / workspace.request().stage_name


def _continue(workspace, profile, predecessor, *, guard=None, fence="fence-1"):
    return continuation.continue_staging(
        workspace.request(), profile.shared_roots, predecessor=predecessor,
        agent_id="agent-1", fence=fence, require_live_owner=guard or _guard(workspace),
    )


def _bytes(root):
    return {path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mode)
            for path in root.rglob("*") if path.is_file()}


def _first(tmp_path):
    workspace, profile, _ = _workspace(tmp_path)
    staging = _staging(workspace)
    (staging / "assembled").mkdir()
    payload = staging / "assembled/values.npy"
    payload.write_bytes(b"a previously verified assembled resource")
    (staging / "assembled/received.json").write_bytes(b'{"resource":"values.npy"}')
    inode = payload.stat().st_ino
    reference = _retain(tmp_path, workspace, profile)
    return workspace, profile, staging, reference, inode


def test_three_attempt_handoff_preserves_payloads_and_immutable_recovery(tmp_path, monkeypatch):
    first, profile, staging, a, inode = _first(tmp_path)
    a_root = recovery.resolve(a, profile.shared_roots)
    immutable_a = _bytes(a_root)
    second, profile, _ = _workspace(tmp_path, attempt=2, predecessors=[a])
    # Initial artifact-root setup is allowed before the continuation operation.
    _staging(second)
    middle = _continue(second, profile, a)
    assert not staging.exists()
    assert (middle / "assembled/values.npy").stat().st_ino == inode
    (middle / "assembled/additional.npy").write_bytes(b"new resource")
    added_inode = (middle / "assembled/additional.npy").stat().st_ino
    b = _retain(tmp_path, second, profile)
    b_root = recovery.resolve(b, profile.shared_roots)
    immutable_b = _bytes(b_root)

    third, profile, _ = _workspace(tmp_path, attempt=3, predecessors=[a, b])
    unbound = replace(third.request(), worker_metadata={
        **third.request().worker_metadata,
        recovery.WIRE: {**third.request().worker_metadata[recovery.WIRE], "predecessors": []},
    })
    with _retention_database(tmp_path / "retention.sqlite") as connection:
        delivered = recovery._bind_delivery(
            unbound, connection, "file:///fixture", profile.shared_roots,
            agent_id="agent-1", slurm_assignments=None,
        )
    assert thaw_plain_data(delivered.worker_metadata[recovery.WIRE]["predecessors"]) == [a, b]
    assert delivered == third.request()
    # Exercise exactly the coordinator-produced delivery, without constructing
    # a new process or pretending this is a physical provider-release test.
    final = continuation.continue_staging(
        delivered, profile.shared_roots, predecessor=b, agent_id="agent-1",
        fence="fence-1", require_live_owner=_guard(third),
    )
    assert not middle.exists()
    assert (final / "assembled/values.npy").stat().st_ino == inode
    assert (final / "assembled/values.npy").read_bytes() == b"a previously verified assembled resource"
    assert (final / "assembled/additional.npy").stat().st_ino == added_inode
    assert _bytes(a_root) == immutable_a
    assert _bytes(b_root) == immutable_b
    assert json.loads((final / RECEIPT).read_text())["identity"]["assignment_id"] == third.assignment_id

    def no_rename(*args, **kwargs):
        raise AssertionError("acknowledgement replay renamed the payload again")

    monkeypatch.setattr(continuation.os, "rename", no_rename)
    assert continuation.continue_staging(
        delivered, profile.shared_roots, predecessor=b, agent_id="agent-1",
        fence="fence-1", require_live_owner=_guard(third),
    ) == final


@pytest.mark.parametrize("boundary", ["intent", "initializer", "rename", "before_marker", "after_marker", "directory", "owner"])
def test_uncertain_handoff_replays_without_copying(tmp_path, monkeypatch, boundary):
    _, profile, source, reference, inode = _first(tmp_path)
    second, profile, _ = _workspace(tmp_path, attempt=2, predecessors=[reference])
    destination = _staging(second)
    atomic = continuation.atomic_write_bytes
    rename = continuation.os.rename
    unlink = Path.unlink
    guard = _guard(second)

    def interrupted_write(path, data, **kwargs):
        marker = Path(path).name == RECEIPT
        if boundary == "before_marker" and marker:
            raise OSError("cut before marker")
        atomic(path, data, **kwargs)
        if (boundary == "intent" and not marker) or (boundary == "after_marker" and marker):
            raise OSError("cut after metadata replacement")

    def interrupted_rename(old, new):
        rename(old, new)
        if boundary == "rename":
            raise OSError("cut after rename")

    def interrupted_unlink(path, **kwargs):
        unlink(path, **kwargs)
        if boundary == "initializer" and path == destination / RECEIPT:
            raise OSError("cut after removing initializer")

    def live():
        owner = guard()
        if boundary == "owner" and not source.exists():
            raise QueueConflictError("cut after ownership changed")
        return owner

    with monkeypatch.context() as patch:
        patch.setattr(continuation, "atomic_write_bytes", interrupted_write)
        patch.setattr(continuation.os, "rename", interrupted_rename)
        patch.setattr(Path, "unlink", interrupted_unlink)
        if boundary == "directory":
            from loom.queue import _remote_stage_execution
            sync = _remote_stage_execution._fsync_directory

            def interrupted_sync(path):
                sync(path)
                if path == source.parent and not source.exists():
                    raise OSError("cut after directory sync")

            patch.setattr(_remote_stage_execution, "_fsync_directory", interrupted_sync)
        with pytest.raises(QueueConflictError, match="cut"):
            _continue(second, profile, reference, guard=live)
    assert _continue(second, profile, reference) == destination
    assert (destination / "assembled/values.npy").stat().st_ino == inode
    assert not source.exists()


def test_failed_intent_directory_sync_is_repaired_before_rename(tmp_path, monkeypatch):
    from loom.pipeline.stores import atomic

    _, profile, source, reference, inode = _first(tmp_path)
    second, profile, _ = _workspace(tmp_path, attempt=2, predecessors=[reference])
    sync = atomic._fsync_path_strict

    def interrupted(path):
        sync(path)
        if path == source:
            raise OSError("cut after journal directory creation")

    with monkeypatch.context() as patch:
        patch.setattr(atomic, "_fsync_path_strict", interrupted)
        with pytest.raises(QueueConflictError, match="journal directory"):
            _continue(second, profile, reference)
    assert (source / continuation._INTENTS).is_dir()
    assert list((source / continuation._INTENTS).iterdir()) == []
    destination = _continue(second, profile, reference)
    assert (destination / "assembled/values.npy").stat().st_ino == inode


def test_next_attempt_can_finish_predecessors_interrupted_handoff(tmp_path, monkeypatch):
    _, profile, source, a, inode = _first(tmp_path)
    second, profile, _ = _workspace(tmp_path, attempt=2, predecessors=[a])
    rename = continuation.os.rename

    def interrupted(old, new):
        rename(old, new)
        raise OSError("worker lost after rename")

    with monkeypatch.context() as patch:
        patch.setattr(continuation.os, "rename", interrupted)
        with pytest.raises(QueueConflictError, match="worker lost"):
            _continue(second, profile, a)
    assert not source.exists()
    b = _retain(tmp_path, second, profile)
    third, profile, _ = _workspace(tmp_path, attempt=3, predecessors=[a, b])
    final = _continue(third, profile, b)
    assert (final / "assembled/values.npy").stat().st_ino == inode
    assert json.loads((final / RECEIPT).read_text())["identity"]["assignment_id"] == third.assignment_id


def test_handoff_resolves_a_different_host_root_prefix(tmp_path):
    _, profile, _, reference, inode = _first(tmp_path)
    second, profile, _ = _workspace(tmp_path, attempt=2, predecessors=[reference])
    relocated = tmp_path / "other-host-root"
    shutil.move(profile.shared_roots["outputs"]["host_path"], relocated)
    profile = replace(profile, shared_roots={
        "outputs": {**profile.shared_roots["outputs"], "host_path": str(relocated)},
    })
    destination = _continue(second, profile, reference)
    assert destination.is_relative_to(relocated)
    assert (destination / "assembled/values.npy").stat().st_ino == inode


def test_repeated_interrupted_handoffs_keep_intents_with_payloads(tmp_path, monkeypatch):
    _, profile, first_source, a, inode = _first(tmp_path)
    references = [a]
    abandoned = []
    for attempt in (2, 3):
        workspace, profile, _ = _workspace(tmp_path, attempt=attempt, predecessors=references)
        rename = continuation.os.rename

        def interrupted(old, new):
            abandoned.append(old.parent)
            rename(old, new)
            raise OSError("interrupted handoff")

        with monkeypatch.context() as patch:
            patch.setattr(continuation.os, "rename", interrupted)
            with pytest.raises(QueueConflictError, match="interrupted handoff"):
                _continue(workspace, profile, references[-1])
        references.append(_retain(tmp_path, workspace, profile))
    # Completed moves do not pin their empty former artifact directories. Native
    # recovery receipts live elsewhere, and the next handoff must not need them.
    for directory in abandoned:
        shutil.rmtree(directory)
    fourth, profile, _ = _workspace(tmp_path, attempt=4, predecessors=references)
    destination = _continue(fourth, profile, references[-1])
    assert not first_source.exists()
    assert (destination / "assembled/values.npy").stat().st_ino == inode
    assert len(list((destination / continuation._INTENTS).glob("*.json"))) == 3


def test_cross_device_rename_never_falls_back_to_payload_copy(tmp_path, monkeypatch):
    _, profile, source, reference, inode = _first(tmp_path)
    second, profile, _ = _workspace(tmp_path, attempt=2, predecessors=[reference])

    def cross_device(*args):
        raise OSError(errno.EXDEV, "different filesystem")

    with monkeypatch.context() as patch:
        patch.setattr(continuation.os, "rename", cross_device)
        with pytest.raises(QueueConflictError, match="different filesystem"):
            _continue(second, profile, reference)
    assert (source / "assembled/values.npy").stat().st_ino == inode
    destination = _continue(second, profile, reference)
    assert (destination / "assembled/values.npy").stat().st_ino == inode


def test_replay_uses_moved_intent_when_mount_setup_recreated_empty_source(tmp_path):
    _, profile, source, reference, inode = _first(tmp_path)
    second, profile, _ = _workspace(tmp_path, attempt=2, predecessors=[reference])
    destination = _continue(second, profile, reference)
    source.mkdir(parents=True)
    assert _continue(second, profile, reference) == destination
    assert list(source.iterdir()) == []
    assert (destination / "assembled/values.npy").stat().st_ino == inode


def test_empty_mount_destination_needs_no_worker_initializer(tmp_path):
    _, profile, _, reference, inode = _first(tmp_path)
    second, profile, _ = _workspace(tmp_path, attempt=2, predecessors=[reference])
    destination = publication.staging_tree(second.request(), profile.shared_roots, "agent-1")
    destination.mkdir(parents=True)
    assert _continue(second, profile, reference) == destination
    assert (destination / "assembled/values.npy").stat().st_ino == inode


@pytest.mark.parametrize("conflict", ["destination", "published", "sealed", "unauthorized", "owner", "fence", "receipt", "intent_link"])
def test_handoff_refuses_conflicts_without_changing_saved_output(tmp_path, conflict):
    _, profile, source, reference, _ = _first(tmp_path)
    second, profile, _ = _workspace(tmp_path, attempt=2, predecessors=[] if conflict == "unauthorized" else [reference])
    destination = _staging(second)
    if conflict == "destination":
        (destination / "new-output").write_bytes(b"owned by this attempt")
    elif conflict == "published":
        owner = continuation._publication_owner(reference)
        (Path(profile.shared_roots["outputs"]["host_path"]) / "loom-artifacts" / publication.publication_id(owner)).mkdir(parents=True)
    elif conflict == "sealed":
        value = json.loads((source / RECEIPT).read_text())
        (source / RECEIPT).write_bytes(encoded({**value, "members": [], "outputs": {}}))
    elif conflict == "receipt":
        marker = recovery.resolve(reference, profile.shared_roots) / RECEIPT
        marker.chmod(0o600)
        marker.write_bytes(b"{}")
    elif conflict == "intent_link":
        outside = tmp_path / "outside"
        outside.mkdir()
        (source / continuation._INTENTS).symlink_to(outside, target_is_directory=True)

    before_source, before_destination = _bytes(source), _bytes(destination)

    def reject_owner():
        raise QueueConflictError("stale assignment")

    with pytest.raises(QueueConflictError):
        _continue(second, profile, reference, guard=reject_owner if conflict == "owner" else None,
                  fence="changed" if conflict == "fence" else "fence-1")
    assert _bytes(source) == before_source
    assert _bytes(destination) == before_destination
    assert not (destination / continuation._INTENTS).exists()
    if conflict == "intent_link":
        assert list(outside.iterdir()) == []


def test_provider_release_is_required_before_a_predecessor_can_be_delivered(tmp_path):
    _, profile, _, reference, _ = _first(tmp_path)
    second, profile, _ = _workspace(tmp_path, attempt=2)
    with _retention_database(tmp_path / "retention.sqlite") as connection:
        connection.execute("UPDATE remote_assignments SET provider_release_proof_json=NULL")
        with pytest.raises(QueueConflictError, match="positively settled"):
            recovery._bind_delivery(
                second.request(), connection, "file:///fixture", profile.shared_roots,
                agent_id="agent-1", slurm_assignments=None,
            )
    assert recovery.resolve(reference, profile.shared_roots).is_dir()
