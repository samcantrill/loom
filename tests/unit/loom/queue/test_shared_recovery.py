"""Recovery uses native ownership and publication IO, independently of success."""

from dataclasses import replace
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest

from loom.pipeline.stores.shared_artifacts import publication_path_is_retained
from loom.queue import _shared_recovery as recovery
from loom.queue._agent_process_supervisor import _launch_value
from loom.queue._remote_stage_execution import _ResidentAssignmentWorkspace
from loom.queue.errors import QueueConflictError
from tests.unit.loom.queue.test_remote_stage_execution import (
    _shared_publication_workspace,
)


def _workspace(tmp_path, *, attempt=1, predecessors=(), container=False, prefix=False, limits=None):
    base, profile, launch, _ = _shared_publication_workspace(
        tmp_path, container=container, assignment_id=f"fixture-{attempt}", limits=limits
    )
    if prefix:
        roots = {
            key: {
                **value,
                "host_path": str(
                    Path("/proc/self/root") / Path(value["host_path"]).relative_to("/")
                ),
            }
            for key, value in cast(dict[str, Any], profile.shared_roots).items()
        }
        profile = replace(profile, shared_roots=roots)
    request = base.request()
    assignment = f"recovery-{attempt}"
    attempt_id = f"attempt-{attempt}"
    request = replace(
        request,
        assignment_id=assignment,
        attempt_id=attempt_id,
        attempt=attempt,
        worker_metadata={
            **request.worker_metadata,
            "loom.execution_binding": {
                **cast(Any, request.worker_metadata["loom.execution_binding"]),
                "attempt": attempt,
            },
            recovery.WIRE: {
                "schema_version": 1,
                "root_id": "outputs",
                "tree": f"loom-work/{hashlib.sha256(b'agent-1').hexdigest()}/{assignment}/{attempt_id}/recovery",
                "predecessors": list(predecessors),
            },
        },
    )
    workspace = _ResidentAssignmentWorkspace(tmp_path / "agent", assignment)
    workspace.persist_request(request, profile)
    workspace.stage_input("input-1", b"input")
    workspace.accept()
    workspace.grant("fence-1")
    launch = replace(
        launch,
        assignment_id=assignment,
        workspace_root=workspace.root,
        profile=profile.launch_profile,
        bundle_digest=hashlib.sha256(
            json.dumps(
                request.to_dict(), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
    )
    workspace.persist_supervisor_launch(json.dumps(_launch_value(launch)))
    workspace.mark_process_started("execution-1", 101)
    return workspace, profile, launch


def _write(workspace):
    binding = cast(
        Any, workspace.worker_request(resolve_shared=True).metadata[recovery.BINDING]
    )
    current = Path(binding["current"]["path"])
    (current / "checkpoints").mkdir()
    (current / "checkpoints" / "completed").write_bytes(b"complete")
    (current / "partial").write_bytes(b"partial")
    return current


def _retention_database(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agent_receipts (
            principal_id TEXT, operation TEXT, idempotency_key TEXT,
            digest TEXT, result_json TEXT,
            PRIMARY KEY (principal_id, operation, idempotency_key));
        CREATE TABLE IF NOT EXISTS remote_assignments (
            assignment_id TEXT, run_uri TEXT, stage_name TEXT, attempt INTEGER,
            attempt_id TEXT, state TEXT, provider_release_proof_json TEXT,
            report_json TEXT, fence TEXT, start_permitted INTEGER);
        CREATE TABLE IF NOT EXISTS agent_deliveries (assignment_id TEXT, request_json TEXT);
    """)
    return conn


@pytest.mark.parametrize("budget,limit", [
    ("max_payload_bytes", 1), ("max_members", 1), ("max_manifest_bytes", 1024),
    ("max_manifest_bytes", 64),
])
def test_budget_failure_is_durable_unavailable_not_sealed_recovery(
    tmp_path, monkeypatch, budget, limit,
):
    limits = {"max_payload_bytes": 4096, "max_members": 100, "max_manifest_bytes": 4096}
    limits[budget] = limit
    workspace, profile, _ = _workspace(tmp_path, limits=limits)
    current = _write(workspace)
    for index in range(12):
        (current / f"checkpoint-{index}").write_bytes(b"progress")
    before = {str(p.relative_to(current)): p.read_bytes() for p in current.rglob("*") if p.is_file()}
    database = tmp_path / "retention.sqlite"
    row = {"provider_release_proof_json": "positive-exact-proof", "fence": "fence-1"}
    with _retention_database(database) as conn:
        recovery.retain_released(conn, row, workspace.request(), profile.shared_roots, agent_id="agent-1")
        record, = conn.execute("SELECT operation, result_json, digest FROM agent_receipts").fetchall()
        failure = json.loads(record["result_json"])
        assert record["operation"] == "seal_unavailable"
        assert record["digest"] == hashlib.sha256(record["result_json"].encode()).hexdigest()
        assert failure["reason"] == {
            "code": "budget_exceeded", "budget": budget, "limit": limit,
            "observed_at_least": failure["reason"]["observed_at_least"],
        }
        assert failure["reason"]["observed_at_least"] > limit
        assert failure["tree"] == str(current.relative_to(Path(profile.shared_roots["outputs"]["host_path"])))
        assert failure["identity"]["fence"] == "fence-1"
        assert failure["budgets"] == limits
        assert "receipt_digest" not in failure
    conn.close()
    assert {str(p.relative_to(current)): p.read_bytes() for p in current.rglob("*") if p.is_file()} == before
    assert publication_path_is_retained(current)
    assert not (current.parents[4] / "loom-recovery-retained").exists()

    def no_rescan(*args, **kwargs):
        raise AssertionError("acknowledgement replay rescanned unavailable recovery")

    monkeypatch.setattr(recovery, "inventory", no_rescan)
    with _retention_database(database) as reopened:
        recovery.retain_released(reopened, row, workspace.request(), profile.shared_roots, agent_id="agent-1")
        assert reopened.execute("SELECT COUNT(*) FROM agent_receipts").fetchone()[0] == 1
        with pytest.raises(QueueConflictError, match="replay conflicts"):
            recovery.retain_released(reopened, {**row, "fence": "obsolete"}, workspace.request(),
                                     profile.shared_roots, agent_id="agent-1")
    reopened.close()


@pytest.mark.parametrize("damage", ["ownership", "link", "io"])
def test_retention_does_not_downgrade_integrity_or_io_failure(tmp_path, monkeypatch, damage):
    from loom.pipeline.stores.errors import ArtifactStoreError

    limits = {"max_payload_bytes": 1 if damage == "ownership" else 4096,
              "max_members": 100, "max_manifest_bytes": 4096}
    workspace, profile, _ = _workspace(tmp_path, limits=limits)
    current = _write(workspace)
    if damage == "link":
        (current / "external").symlink_to(tmp_path / "outside")
    if damage == "io":
        def failed_read(*args, **kwargs):
            raise OSError("storage unavailable")
        monkeypatch.setattr(recovery, "inventory", failed_read)
    with _retention_database(tmp_path / "retention.sqlite") as conn:
        with pytest.raises((ArtifactStoreError, QueueConflictError, OSError)):
            recovery.retain_released(
                conn, {"provider_release_proof_json": "proof", "fence": "obsolete" if damage == "ownership" else "fence-1"},
                workspace.request(), profile.shared_roots, agent_id="agent-1",
            )
        assert conn.execute("SELECT COUNT(*) FROM agent_receipts").fetchone()[0] == 0
    conn.close()
    assert (current / "partial").read_bytes() == b"partial"


def test_container_command_replay_does_not_recreate_writable_mounts(tmp_path):
    from loom.queue._agent_process_supervisor import _launch_from_value
    from loom.queue._container_worker import prepare_container_worker_paths
    from loom.queue._shared_publication import staging_tree

    workspace, profile, launch = _workspace(tmp_path, container=True)
    current = recovery.current_tree(workspace.request(), profile.shared_roots, agent_id="agent-1")
    staging = staging_tree(workspace.request(), profile.shared_roots, "agent-1")
    assert not current.exists() and not staging.exists()
    original_digest, original_argv = launch.spec_digest, launch.command_argv
    prepare_container_worker_paths(profile.launch_profile, workspace=workspace.root, agent_id="agent-1")
    assert current.is_dir() and staging.is_dir()
    current.rmdir()
    staging.rmdir()
    retained = workspace.supervisor_launch_json()
    assert retained is not None
    restored = _launch_from_value(json.loads(retained))
    assert restored.spec_digest == original_digest
    assert restored.command_argv == original_argv
    assert not current.exists() and not staging.exists()


def test_interrupted_seal_replays_without_worker_result_and_preserves_every_member(
    tmp_path, monkeypatch
):
    workspace, profile, _ = _workspace(tmp_path)
    current = _write(workspace)
    assert workspace.worker_result() is None
    original = recovery.os.rename

    def interrupt(source, target):
        original(source, target)
        raise OSError("interrupted after rename before retention transaction")

    with monkeypatch.context() as patch:
        patch.setattr(recovery.os, "rename", interrupt)
        with pytest.raises(OSError, match="interrupted"):
            recovery.seal(
                workspace.request(),
                profile.shared_roots,
                agent_id="agent-1",
                fence="fence-1",
            )
    import loom.queue._remote_stage_execution as remote_execution

    synced = []
    sync_directory = remote_execution._fsync_directory

    def observe_sync(path):
        sync_directory(path)
        synced.append(path)

    monkeypatch.setattr(remote_execution, "_fsync_directory", observe_sync)
    reopened = _ResidentAssignmentWorkspace(tmp_path / "agent", workspace.assignment_id)
    ref = recovery.seal(
        reopened.request(), profile.shared_roots, agent_id="agent-1", fence="fence-1"
    )
    assert (
        recovery.seal(
            reopened.request(),
            profile.shared_roots,
            agent_id="agent-1",
            fence="fence-1",
        )
        == ref
    )
    retained = recovery.resolve(ref, profile.shared_roots)
    assert {retained.parent, retained.parent.parent, current.parent}.issubset(synced)
    assert not current.exists()
    assert (retained / "checkpoints" / "completed").read_bytes() == b"complete"
    assert (retained / "partial").read_bytes() == b"partial"
    assert (retained / "partial").stat().st_mode & 0o222 == 0
    assert retained.stat().st_mode & 0o222 == 0
    assert publication_path_is_retained(retained)
    assert publication_path_is_retained(retained / "checkpoints" / "completed")
    assert publication_path_is_retained(retained.parent)


@pytest.mark.parametrize("damage", ["missing", "corrupt", "receipt", "extra"])
def test_closed_recovery_rejects_missing_corrupt_or_changed_members(tmp_path, damage):
    workspace, profile, _ = _workspace(tmp_path)
    _write(workspace)
    ref = recovery.seal(
        workspace.request(), profile.shared_roots, agent_id="agent-1", fence="fence-1"
    )
    assert ref is not None
    tree = recovery.resolve(ref, profile.shared_roots)
    tree.chmod(0o755)
    (tree / "checkpoints").chmod(0o755)
    (tree / "checkpoints" / "completed").chmod(0o644)
    (tree / ".loom-publication.json").chmod(0o644)
    if damage == "missing":
        (tree / "checkpoints" / "completed").unlink()
    elif damage == "corrupt":
        (tree / "checkpoints" / "completed").write_bytes(b"changed")
    elif damage == "extra":
        (tree / "late").write_bytes(b"late")
    else:
        (tree / ".loom-publication.json").write_bytes(b"{}")
    with pytest.raises(QueueConflictError, match="integrity"):
        recovery.resolve(ref, profile.shared_roots)
    with pytest.raises(QueueConflictError, match="replay"):
        recovery.seal(
            workspace.request(),
            profile.shared_roots,
            agent_id="agent-1",
            fence="fence-1",
        )


@pytest.mark.parametrize("increase_limits", [False, True])
def test_retry_binding_resolves_other_prefix_and_mounts_only_exact_readonly_predecessor(
    tmp_path, increase_limits,
):
    workspace, profile, _ = _workspace(tmp_path)
    _write(workspace)
    ref = recovery.seal(
        workspace.request(), profile.shared_roots, agent_id="agent-1", fence="fence-1"
    )
    assert ref is not None
    successor, alternate, _ = _workspace(
        tmp_path, attempt=2, predecessors=[ref], prefix=True,
        limits={"max_members": 1_000_000, "max_payload_bytes": 274_877_906_944,
                "max_manifest_bytes": 536_870_912} if increase_limits else None,
    )
    bound = cast(
        Any, successor.worker_request(resolve_shared=True).metadata[recovery.BINDING]
    )
    assert len(bound["predecessors"]) == 1
    assert bound["predecessors"][0]["attempt"] == 1
    assert bound["predecessors"][0]["reference"] == ref
    assert (
        Path(bound["predecessors"][0]["path"]) / "partial"
    ).read_bytes() == b"partial"
    # Build the real container command against the exact same portable binding.
    from loom.queue._container_worker import build_container_worker

    image = tmp_path / "worker.sif"
    image.write_bytes(b"command fixture")
    from dataclasses import replace

    launch_profile = replace(
        alternate.launch_profile,
        container={
            "kind": "apptainer",
            "container": {"image": {"reference": str(image)}},
            "options": {"command": "/usr/bin/apptainer"},
            "python_executable": "/python",
            "daemon_endpoint": None,
        },
    )
    from loom.queue.shared_execution import assignment_scope

    argv = build_container_worker(
        launch_profile,
        workspace=successor.root,
        worker=("/python",),
        environment={},
        shared_scope=assignment_scope(successor.request().fingerprint),
        agent_id="agent-1",
    ).argv
    assert any(str(ref["tree"]) in arg and arg.endswith(":ro") for arg in argv)
    assert any(
        "/recovery-2/attempt-2/recovery" in arg and arg.endswith(":rw") for arg in argv
    )
    assert not any(arg.startswith(str(tmp_path / "shared") + ":") for arg in argv)


def test_uncertain_liveness_and_obsolete_fence_cannot_retain_or_rebind(tmp_path):
    workspace, profile, _ = _workspace(tmp_path)
    _write(workspace)
    with pytest.raises(QueueConflictError, match="positive"):
        recovery.retain_released(
            None,
            {"provider_release_proof_json": None},
            workspace.request(),
            profile.shared_roots,
            agent_id="agent-1",
        )
    with pytest.raises(QueueConflictError, match="ownership"):
        recovery.seal(
            workspace.request(),
            profile.shared_roots,
            agent_id="agent-1",
            fence="obsolete",
        )
    assert recovery.current_tree(workspace.request(), profile.shared_roots).exists()
    changed = {
        **cast(Any, workspace.request().worker_metadata[recovery.WIRE]),
        "tree": "loom-recovery/other/attempt",
    }
    with pytest.raises(QueueConflictError, match="ownership"):
        replace(
            workspace.request(),
            worker_metadata={
                **workspace.request().worker_metadata,
                recovery.WIRE: changed,
            },
        )


@pytest.mark.parametrize("mount_created", [False, True])
def test_early_death_has_an_empty_closure_only_after_positive_release(
    tmp_path, mount_created
):
    workspace, profile, _ = _workspace(tmp_path)
    assert workspace.worker_result() is None
    if mount_created:
        recovery.current_tree(workspace.request(), profile.shared_roots).mkdir(
            parents=True
        )
    # No child binding means no scientific files; native settlement may still
    # retain the exact empty attempt instead of manufacturing progress.
    ref = recovery.seal(
        workspace.request(), profile.shared_roots, agent_id="agent-1", fence="fence-1"
    )
    assert ref is not None
    tree = recovery.resolve(ref, profile.shared_roots)
    assert json.loads((tree / ".loom-publication.json").read_text())["members"] == []


def test_current_tree_uses_stable_machine_partition_and_rejects_other_machine(tmp_path):
    workspace, profile, _ = _workspace(tmp_path)
    request = workspace.request()
    from loom.queue._shared_publication import staging_relative

    first = recovery.current_relative(request, "agent-1")
    other = recovery.current_relative(request, "agent-2")
    assert first != other
    assert (
        Path(first).parent == Path(staging_relative(request, "agent-1")).parent.parent
    )
    assert first.split("/")[1] == hashlib.sha256(b"agent-1").hexdigest()
    with pytest.raises(QueueConflictError, match="machine ownership"):
        recovery.current_tree(request, profile.shared_roots, agent_id="agent-2")
    with pytest.raises(QueueConflictError, match="machine ownership"):
        recovery.seal(
            request, profile.shared_roots, agent_id="agent-2", fence="fence-1"
        )


def test_recovery_preview_inventory_does_not_read_payloads(tmp_path, monkeypatch):
    workspace, profile, _ = _workspace(tmp_path)
    _write(workspace)
    ref = recovery.seal(
        workspace.request(), profile.shared_roots, agent_id="agent-1", fence="fence-1"
    )

    def reject_payload_scan(*args, **kwargs):
        raise AssertionError("metadata inspection scanned recovery payloads")

    monkeypatch.setattr(recovery, "inventory", reject_payload_scan)
    tree, receipt = recovery.inspect(ref, profile.shared_roots)
    assert tree.is_dir()
    assert sum(row["size_bytes"] for row in receipt["members"]) == len(b"completepartial")
    assert {row["path"] for row in receipt["members"]} == {"checkpoints/completed", "partial"}
    assert publication_path_is_retained(tree)


def test_retention_preparation_has_no_receipt_writes_and_commit_is_exact(tmp_path):
    workspace, profile, _ = _workspace(tmp_path)
    _write(workspace)
    row = {"provider_release_proof_json": "positive-exact-proof", "fence": "fence-1"}
    with _retention_database(tmp_path / "retention.sqlite") as conn:
        prepared = recovery.prepare_retention(
            conn, row, workspace.request(), profile.shared_roots, agent_id="agent-1",
        )
        assert prepared is not None
        assert conn.execute("SELECT COUNT(*) FROM agent_receipts").fetchone()[0] == 0
        recovery.commit_retention(conn, prepared)
        recovery.commit_retention(conn, prepared)
        assert conn.execute("SELECT COUNT(*) FROM agent_receipts").fetchone()[0] == 1
        with pytest.raises(QueueConflictError, match="outcome replay conflicts"):
            recovery.commit_retention(conn, replace(prepared, digest="conflicting"))


def test_committed_retention_replay_validates_receipt_without_resealing(tmp_path, monkeypatch):
    workspace, profile, _ = _workspace(tmp_path)
    _write(workspace)
    row = {"provider_release_proof_json": "positive-exact-proof", "fence": "fence-1"}
    database = tmp_path / "retention.sqlite"
    with _retention_database(database) as conn:
        recovery.retain_released(conn, row, workspace.request(), profile.shared_roots, agent_id="agent-1")
    monkeypatch.setattr(recovery, "seal", lambda *args, **kwargs: pytest.fail("replayed committed seal"))
    with _retention_database(database) as conn:
        recovery.retain_released(conn, row, workspace.request(), profile.shared_roots, agent_id="agent-1")
        with pytest.raises(QueueConflictError, match="binding conflicts"):
            recovery.retain_released(conn, {**row, "fence": "other"}, workspace.request(), profile.shared_roots, agent_id="agent-1")
