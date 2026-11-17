"""Stopped upgrades preserve native owners across partial publication and restore."""

from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import shutil
import socket
import sqlite3
import time
from typing import Any

import pytest

from loom.pipeline.executors.slurm.ready_stage import SlurmReadyStageProfile
from loom.pipeline.stores.coordinator_authority import EmbeddedCoordinatorAuthorityFactory
from loom.queue import LocalDaemon
from loom.queue._agent_session_journal import _RemoteAgentJournal
from loom.queue._agent_slurm import SlurmSubmissionProjection
from loom.queue._storage_upgrade_state import GUARD_NAME, require_storage_upgrade_ready
from loom.queue.agent_session_transport import LocalDaemonAgentHttpClient
from loom.queue.deployment import load_coordinator_service_config, load_outbound_agent_service_config, _slurm_profile_composition
from loom.queue.errors import QueueError, QueueServiceError
from loom.queue.local_daemon import _acquire_lock, _open_root, _validate_deployment_binding
from loom.queue.storage_upgrade import storage_upgrade
from loom.queue import storage_upgrade as upgrade_module
from tests.unit.loom.queue.test_deployment import (
    _agent_config, _coordinator_config, _rollback_storage, _write_protected,
)


def _agent_root(service) -> Path:
    root = service.client.agent_root
    assert isinstance(root, Path)
    return root


@pytest.fixture
def root(tmp_path_factory):
    # Short enough for native Unix sockets; the caller selects pytest basetemp.
    return tmp_path_factory.mktemp("upgrade")


def _profile():
    return {
        "profile_id": "training", "partition": "cpu", "max_outstanding": 2,
        "runner": {"_target_": "loom.pipeline.executors.slurm.FakeSlurmCommandRunner"},
        "command_adapter_fingerprint": "fake-v1", "bootstrap_principal_id": "bootstrap",
        "credential_reference": "credential", "coordinator_endpoint": "https://coordinator.example",
        "project_fingerprint": "project", "environment_fingerprint": "environment", "executor_fingerprint": "executor",
        "job_private_file_provider": {
            "_target_": "loom.pipeline.executors.slurm.ready_stage.SlurmJobPrivateFileProvider",
            "fixed_path": "/run/test-capability", "descriptor": "test-v1", "helper_argv": ["/bin/true"],
        },
    }


def _cohort(root, *, kind="slurm", explicit_wal=False, legacy=False, custom_provider=False,
            pending_effects=False, replayable_start=False, bootstrap_upgrade=False, terminal_recovery=False,
            async_output=False, source_replayable_start=False):
    c, a = root / "c", root / "a"
    c.mkdir(mode=0o700)
    a.mkdir(mode=0o700)
    source_c = _coordinator_config(c)
    payload = json.loads(source_c.read_text())
    payload["local_agent"] = None
    if pending_effects or replayable_start or async_output or source_replayable_start:
        payload["slurm_admission"] = {"max_reserved_gpus": 8}
        payload["agent_policy"]["agents"] = [{
            "credential_id": "credential", "principal_id": "principal",
            "agent_id": "submit-agent", "pools": ["default"],
            "capabilities": ["slurm-agent-jobs-v1"], "gpu_devices": [],
        }]
        if source_replayable_start:
            payload["agent_policy"]["agents"][0]["capabilities"].extend([
                "slurm-pending-effects-v1", "slurm-replayable-start-v1",
            ])
    (c / "authority").mkdir(mode=0o700)
    payload["authority"]["state_root"] = "authority"
    if explicit_wal:
        payload["storage"] = _rollback_storage()
        payload["storage"]["sqlite"]["journal_mode"] = "wal"
    if bootstrap_upgrade:
        payload["slurm_profiles"] = [{**_profile(), "credential_reference": "bootstrap-credential"}]
        profile, = _slurm_profile_composition(payload["slurm_profiles"])
        assert isinstance(profile, SlurmReadyStageProfile)
        payload["agent_policy"]["agents"][0]["external_slurm_profiles"] = [
            [profile.profile_id, profile.configuration_fingerprint]]
    _write_protected(source_c, payload)
    coordinator = load_coordinator_service_config(source_c)
    LocalDaemon.initialize_deployment(coordinator.daemon)
    with coordinator.daemon.connect_database(coordinator.daemon.control_database) as conn:
        from loom.queue._maintenance import _KEY
        gate = json.loads(conn.execute("SELECT value FROM daemon_metadata WHERE key=?", (_KEY,)).fetchone()[0])
        gate.update(state="closed", revision=1, maintenance_id="upgrade-test")
        conn.execute("UPDATE daemon_metadata SET value=? WHERE key=?", (json.dumps(gate), _KEY))
        conn.commit()
    source_a = _agent_config(a)
    agent_payload = json.loads(source_a.read_text())
    if custom_provider:
        agent_payload["provider_factory"] = {
            "_target_": "tests.support.stage29_composition.ResidentProviderFactory", "capacity": 1,
        }
    if kind == "slurm":
        agent_payload["resident_profiles"] = []
    if kind != "resident":
        agent_payload["slurm_profiles"] = [_profile()]
    if bootstrap_upgrade:
        agent_payload["slurm_profiles"][0]["credential_reference"] = "bootstrap-credential"
    if pending_effects or replayable_start or async_output or source_replayable_start:
        agent_payload["registration"]["capabilities"] = ["slurm-agent-jobs-v1"]
        if source_replayable_start:
            agent_payload["registration"]["capabilities"].extend([
                "slurm-pending-effects-v1", "slurm-replayable-start-v1",
            ])
    if explicit_wal:
        agent_payload["storage"] = payload["storage"]
    _write_protected(source_a, agent_payload)
    agent = load_outbound_agent_service_config(source_a)
    LocalDaemonAgentHttpClient.initialize_agent_root(agent.client)
    with agent.client.connect_database(_agent_root(agent) / "control.sqlite") as conn:
        conn.execute("UPDATE root_metadata SET value='drained' WHERE key='availability_state'")
        if legacy:
            conn.execute("DELETE FROM root_metadata WHERE key='execution_store_requirements'")
        conn.commit()
    payload["storage"] = _rollback_storage()
    payload["slurm_admission"] = {"max_reserved_gpus": 8}
    if pending_effects or replayable_start:
        payload["agent_policy"]["agents"][0]["capabilities"].append("slurm-pending-effects-v1")
        agent_payload["registration"]["capabilities"].append("slurm-pending-effects-v1")
    if replayable_start:
        payload["agent_policy"]["agents"][0]["capabilities"].append("slurm-replayable-start-v1")
        agent_payload["registration"]["capabilities"].append("slurm-replayable-start-v1")
    if async_output:
        payload["agent_policy"]["agents"][0]["capabilities"].append("slurm-pending-output-v1")
        agent_payload["registration"]["capabilities"].append("slurm-pending-output-v1")
    if terminal_recovery:
        payload["slurm_terminal_recovery"] = {"terminal_result_grace_seconds": 120}
    if bootstrap_upgrade:
        payload["slurm_profiles"][0]["bootstrap_executable"] = "/new/immutable/loom"
        agent_payload["slurm_profiles"][0]["bootstrap_executable"] = "/new/immutable/loom"
        profile, = _slurm_profile_composition(payload["slurm_profiles"])
        assert isinstance(profile, SlurmReadyStageProfile)
        payload["agent_policy"]["agents"][0]["external_slurm_profiles"] = [
            [profile.profile_id, profile.configuration_fingerprint]]
    target_c = _write_protected(c / "target.yaml", payload)
    agent_payload["storage"] = _rollback_storage()
    target_a = _write_protected(a / "target.yaml", agent_payload)
    ids = [
        _open_root(coordinator.daemon.coordinator_root, role="coordinator"),
        _open_root(_agent_root(agent), role="local-agent"),
    ]
    request = _write_protected(root / "request.json", {
        "version": 1, "operation_id": "conversion-1", "snapshot_root": str(root / "snapshots"),
        "roles": [
            {"role": role, "expected_root_id": identity, "source_config": str(source), "target_config": str(target)}
            for role, identity, source, target in zip(
                ("coordinator", "outbound-agent"), ids, (source_c, source_a), (target_c, target_a), strict=True,
            )
        ],
    })
    return request, coordinator, agent, load_coordinator_service_config(target_c), load_outbound_agent_service_config(target_a)


def _snapshot(root):
    return {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("version", [5, 6, 7])
def test_pending_effects_supported_upgrade_and_restore(root, version):
    request, old_c, _, new_c, _ = _cohort(root, pending_effects=True, replayable_start=version >= 6, terminal_recovery=version == 7)
    assert old_c.daemon.slurm_schema_version == 4
    assert new_c.daemon.slurm_schema_version == version
    assert storage_upgrade(request)["state"] == "eligible"
    assert storage_upgrade(request, action="apply")["state"] == "ready"
    _validate_deployment_binding(new_c.daemon)
    from loom.queue.slurm_ready_stage import SQLiteSlurmStageAssignments
    store = SQLiteSlurmStageAssignments(
        new_c.daemon.execution_database, root / "transfers", schema_version=version,
        sqlite_policy=new_c.daemon.sqlite_policy, _allow_initialize=False,
    )
    store._open_existing()
    assert store.pending_storage_page() == ()
    SlurmSubmissionProjection(
        new_c.daemon.execution_database, schema_version=version,
        sqlite_policy=new_c.daemon.sqlite_policy,
    )._open_existing()
    assert storage_upgrade(request, action="restore")["state"] == "restored"
    _validate_deployment_binding(old_c.daemon)
    with closing(sqlite3.connect(old_c.daemon.execution_database)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone() == (4,)


@pytest.mark.parametrize("role", ["coordinator", "outbound-agent"])
def test_pending_effects_upgrade_does_not_allow_unrelated_capability(root, role):
    request, *_ = _cohort(root, pending_effects=True, async_output=True)
    declaration = next(item for item in json.loads(request.read_text())["roles"] if item["role"] == role)
    target = Path(declaration["target_config"])
    payload = json.loads(target.read_text())
    registration = (payload["agent_policy"]["agents"][0] if role == "coordinator"
                    else payload["registration"])
    registration["capabilities"].append("unrelated-capability")
    _write_protected(target, payload)
    before = _snapshot(root)
    with pytest.raises(QueueError, match="other declarations must match"):
        storage_upgrade(request)
    assert _snapshot(root) == before


def test_schema_six_upgrade_allows_async_output_and_remains_inspectable(root):
    from loom.queue.service_upgrade import inspect_service_settlement

    request, old_c, _, new_c, new_a = _cohort(
        root, source_replayable_start=True, async_output=True, terminal_recovery=True,
    )
    assert old_c.daemon.slurm_schema_version == 6
    assert new_c.daemon.slurm_schema_version == 7
    assert storage_upgrade(request)["state"] == "eligible"
    assert storage_upgrade(request, action="apply")["state"] == "ready"
    _validate_deployment_binding(new_c.daemon)
    for root_path, role in (
        (new_c.daemon.coordinator_root, "coordinator"),
        (_agent_root(new_a), "local-agent"),
    ):
        assert root_path is not None
        identity = _open_root(root_path, role=role)
        observation = inspect_service_settlement(root_path, expected_root_id=identity)
        assert observation.availability == "available", observation.to_dict()
        assert observation.value["settled"] is True
    assert storage_upgrade(request, action="restore")["state"] == "restored"
    _validate_deployment_binding(old_c.daemon)
    with closing(sqlite3.connect(old_c.daemon.execution_database)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone() == (6,)


def _retained_run(root, coordinator, *, annotated=True, name="run"):
    from loom.pipeline.status import RunStatus
    from loom.pipeline.stores.authority import CoordinatorAdmissionRequest
    from loom.runs.context import SubmissionContext

    run = root / name
    run.mkdir()
    uri = run.as_uri()
    identity = _open_root(coordinator.daemon.coordinator_root, role="coordinator")
    store = coordinator.daemon.coordinator_authority_factory._store(uri)
    store.create_run(uri, status=RunStatus.SUCCEEDED, metadata={"retained": "original-history"})
    with coordinator.daemon.connect_database(coordinator.daemon.control_database) as conn:
        if annotated:
            store.initialize_run_annotations(uri, SubmissionContext(), "prepare-" + name, identity)
            conn.execute(
                "INSERT INTO preparation_operations(operation_id, principal_id, kind, intent_digest, request_json, "
                "selected_json, child_name, state, result_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("prepare-" + name, "operator", "prepare_run", "intent", "{}", "{}", "child-" + name, "applied",
                 json.dumps({"prepared_run": {"run_uri": uri}})),
            )
        else:
            request = CoordinatorAdmissionRequest("admit-run", identity, uri, "intent")
            store.bind_coordinator_admission(uri, request)
            conn.execute(
                "INSERT INTO managed_admissions(admission_id, queue_item_id, coordinator_id, run_uri, "
                "intent_digest, execution_owner, state, accepted_at, authority_operation_id, run_priority, enqueue_sequence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("admission", "run", identity, uri, "intent", "managed-stage", "SUCCEEDED",
                 "2026-01-01T00:00:00Z", "admit-run", 0, 1),
            )
        conn.commit()
    return run, store


def _interrupt_conversion(request, coordinator, monkeypatch):
    copy = upgrade_module._copy_database

    def interrupt(source, target, *, mode):
        copy(source, target, mode=mode)
        if target == coordinator.daemon.control_database:
            raise OSError("interrupted conversion")

    with monkeypatch.context() as patch:
        patch.setattr(upgrade_module, "_copy_database", interrupt)
        with pytest.raises(OSError, match="interrupted conversion"):
            storage_upgrade(request, action="apply")


@pytest.mark.parametrize("kind", ["slurm", "resident", "mixed"])
@pytest.mark.parametrize("explicit_wal", [False, True])
def test_round_trip(root, kind, explicit_wal):
    request, old_c, old_a, new_c, new_a = _cohort(root, kind=kind, explicit_wal=explicit_wal, legacy=True)
    before = _snapshot(root)
    preview = storage_upgrade(request)
    assert preview["state"] == "eligible" and preview["qualified"] is False
    assert _snapshot(root) == before
    assert not (root / "snapshots").exists()
    assert storage_upgrade(request, action="apply")["state"] == "ready"
    _validate_deployment_binding(new_c.daemon)
    for owner in preview["owners"]:
        for name in owner["databases"]:
            with new_c.daemon.connect_database(Path(name)) as conn:
                assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
                assert conn.execute("PRAGMA synchronous").fetchone()[0] == 3
    SlurmSubmissionProjection(new_c.daemon.execution_database, sqlite_policy=new_c.daemon.sqlite_policy, schema_version=4)._open_existing()
    from loom.queue.slurm_ready_stage import SQLiteSlurmStageAssignments
    SQLiteSlurmStageAssignments(new_c.daemon.execution_database, root / "transfers", schema_version=4,
                               sqlite_policy=new_c.daemon.sqlite_policy, _allow_initialize=False)._open_existing()
    if kind != "slurm":
        from loom.queue._agent_process_supervisor import _service_configuration
        assert _service_configuration(_agent_root(new_a) / "supervisor").storage == new_a.client.storage
    assert storage_upgrade(request, action="restore")["state"] == "restored"
    _validate_deployment_binding(old_c.daemon)
    with closing(sqlite3.connect(old_c.daemon.execution_database)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone() == (3,)
    journal = _RemoteAgentJournal(_agent_root(old_a),
        expected_configuration_fingerprint=old_a.immutable_fingerprint,
        expected_active_configuration_fingerprint=old_a.active_fingerprint,
        sqlite_policy=old_a.client.sqlite_policy)
    journal.close()
    assert storage_upgrade(request, action="restore")["state"] == "restored"


@pytest.mark.parametrize("boundary", ["guard", "database", "binding", "ready"])
@pytest.mark.parametrize("finish", ["resume", "restore"])
def test_interruption(root, monkeypatch, boundary, finish):
    request, old_c, old_a, new_c, new_a = _cohort(root, kind="mixed")
    publish = upgrade_module.publish_json
    atomic = upgrade_module.atomic_write_bytes
    copied = upgrade_module._copy_database
    fired = False

    def interrupt():
        nonlocal fired
        if not fired:
            fired = True
            raise OSError("interrupted publication acknowledgement")

    def published(path, value):
        publish(path, value)
        if boundary == "guard" and path.name == GUARD_NAME:
            interrupt()
        if boundary == "ready" and path.name == "manifest.json" and value["state"] == "ready":
            interrupt()

    def copy(source, target, *, mode):
        copied(source, target, mode=mode)
        if boundary == "database" and target == old_c.daemon.control_database:
            interrupt()

    def write(path, payload, **kwargs):
        atomic(path, payload, **kwargs)
        if boundary == "binding" and path.name == "deployment-binding.json":
            interrupt()

    monkeypatch.setattr(upgrade_module, "publish_json", published)
    monkeypatch.setattr(upgrade_module, "_copy_database", copy)
    monkeypatch.setattr(upgrade_module, "atomic_write_bytes", write)
    with pytest.raises(OSError, match="interrupted"):
        storage_upgrade(request, action="apply")
    if boundary != "ready":
        with pytest.raises(QueueServiceError, match="incomplete"):
            LocalDaemon(new_c.daemon).start()
    sources = {str(path): path.read_bytes() for path in (root / "snapshots").glob("*-source*")}
    result = storage_upgrade(request, action=finish)
    assert result["state"] == ("ready" if finish == "resume" else "restored")
    if boundary != "guard":
        assert {str(path): path.read_bytes() for path in (root / "snapshots").glob("*-source*")} == sources
    selected_c, selected_a = (new_c, new_a) if finish == "resume" else (old_c, old_a)
    _validate_deployment_binding(selected_c.daemon)
    journal = _RemoteAgentJournal(_agent_root(selected_a),
        expected_configuration_fingerprint=selected_a.immutable_fingerprint,
        expected_active_configuration_fingerprint=selected_a.active_fingerprint,
        sqlite_policy=selected_a.client.sqlite_policy)
    journal.close()


@pytest.mark.parametrize("owner", ["coordinator", "agent"])
def test_activation_refuses_restore(root, owner):
    request, _, _, coordinator, agent = _cohort(root)
    storage_upgrade(request, action="apply")
    if owner == "coordinator":
        daemon = LocalDaemon(coordinator.daemon)
        daemon.start()
        daemon.stop()
    else:
        journal = _RemoteAgentJournal(_agent_root(agent),
            expected_configuration_fingerprint=agent.immutable_fingerprint,
            expected_active_configuration_fingerprint=agent.active_fingerprint,
            sqlite_policy=agent.client.sqlite_policy)
        journal.close()
    assert storage_upgrade(request)["entered"] is True
    before = _snapshot(root)
    with pytest.raises(QueueServiceError, match="after a target owner entered"):
        storage_upgrade(request, action="restore")
    assert _snapshot(root) == before


def test_lock_and_decl_conflict(root):
    request, coordinator, _, _, _ = _cohort(root)
    with _acquire_lock(coordinator.daemon.coordinator_root):
        with pytest.raises(QueueError, match="locked"):
            storage_upgrade(request, action="apply")
    assert not (root / "snapshots").exists()
    storage_upgrade(request, action="apply")
    selected = json.loads(request.read_bytes())["roles"][0]["target_config"]
    payload = json.loads(Path(selected).read_bytes())
    payload["slurm_admission"]["max_reserved_gpus"] = 9
    _write_protected(Path(selected), payload)
    with pytest.raises(QueueError, match="conflicts"):
        storage_upgrade(request, action="resume")


@pytest.mark.parametrize("annotated", [True, False])
def test_authority_inventory(root, annotated):
    request, coordinator, _, target, _ = _cohort(root)
    from loom.pipeline.status import RunStatus
    selected = coordinator.daemon.coordinator_authority_factory
    assert isinstance(selected, EmbeddedCoordinatorAuthorityFactory)
    run, _ = _retained_run(root, coordinator, annotated=annotated)
    other = EmbeddedCoordinatorAuthorityFactory(selected.state_root, root / "other-deployment")
    other._store(run.as_uri()).create_run(run.as_uri(), status=RunStatus.SUCCEEDED)
    foreign = _snapshot(other.state_root / hashlib.sha256(str(other.deployment_root).encode()).hexdigest())
    preview = storage_upgrade(request)
    assert sum(name.endswith("authority.sqlite3") for name in preview["owners"][0]["databases"]) == 1
    storage_upgrade(request, action="apply")
    assert target.daemon.coordinator_authority_factory is not None
    assert target.daemon.coordinator_authority_factory(run.as_uri()).open_run(run.as_uri()).status == RunStatus.SUCCEEDED
    assert _snapshot(other.state_root / hashlib.sha256(str(other.deployment_root).encode()).hexdigest()) == foreign


@pytest.mark.parametrize("damage", ["missing_namespace", "missing_run", "wrong_hash", "wrong_owner", "unknown_operation", "wrong_operation", "unannotated"])
def test_authority_inventory_refuses_missing_or_unbound_state(root, damage):
    request, coordinator, _, _, _ = _cohort(root)
    run, _ = _retained_run(root, coordinator)
    authority = coordinator.daemon.coordinator_authority_factory
    assert isinstance(authority, EmbeddedCoordinatorAuthorityFactory)
    bucket = authority.state_root / hashlib.sha256(str(authority.deployment_root).encode()).hexdigest()
    child = bucket / hashlib.sha256(run.as_uri().encode()).hexdigest()
    if damage == "wrong_operation":
        _retained_run(root, coordinator, name="other")
    if damage == "missing_namespace":
        shutil.rmtree(bucket)
    elif damage == "missing_run":
        shutil.rmtree(child)
    elif damage == "wrong_hash":
        child.rename(bucket / ("0" * 64))
    else:
        with closing(sqlite3.connect(child / "authority.sqlite3")) as conn, conn:
            if damage == "unannotated":
                conn.execute("DELETE FROM run_annotations")
            else:
                row = conn.execute("SELECT annotations_json FROM run_annotations").fetchone()
                payload = json.loads(row[0])
                key = "initializer_coordinator_id" if damage == "wrong_owner" else "initializer_operation_id"
                payload[key] = "prepare-other" if damage == "wrong_operation" else "different-owner"
                conn.execute("UPDATE run_annotations SET annotations_json=?, initialization_json=?",
                             (json.dumps(payload), json.dumps(payload)))
    before = _snapshot(root)
    with pytest.raises(QueueError, match="embedded authority"):
        storage_upgrade(request, action="apply")
    assert _snapshot(root) == before
    assert not (root / "snapshots").exists()


@pytest.mark.parametrize("action", ["resume", "restore"])
def test_recovery_requires_physical_owner(root, monkeypatch, action):
    request, coordinator, _, _, _ = _cohort(root)
    _interrupt_conversion(request, coordinator, monkeypatch)
    before = _snapshot(root)
    monkeypatch.setattr(socket, "gethostname", lambda: "another-host")
    with pytest.raises(QueueError, match="physical owner host"):
        storage_upgrade(request, action=action)
    assert _snapshot(root) == before


@pytest.mark.parametrize("side", ["source", "target"])
@pytest.mark.parametrize("action", ["resume", "restore"])
def test_recovery_binds_composed_inputs(root, monkeypatch, side, action):
    request, coordinator, _, _, _ = _cohort(root)
    declaration = Path(json.loads(request.read_bytes())["roles"][0][side + "_config"])
    payload = json.loads(declaration.read_bytes())
    included = _write_protected(declaration.parent / "authority.yaml", payload["authority"])
    payload["authority"] = {"_include_": included.name}
    _write_protected(declaration, payload)
    _interrupt_conversion(request, coordinator, monkeypatch)
    _write_protected(included, {"kind": "embedded", "state_root": "other-authority"})
    before = _snapshot(root)
    with pytest.raises(QueueError, match="conflicts"):
        storage_upgrade(request, action=action)
    assert _snapshot(root) == before


def test_target_cannot_add_missing_execution_store(root):
    request, _, agent, _, _ = _cohort(root, kind="resident", custom_provider=True)
    selected = Path(json.loads(request.read_bytes())["roles"][1]["target_config"])
    payload = json.loads(selected.read_bytes())
    payload["slurm_profiles"] = [_profile()]
    _write_protected(selected, payload)
    before = _snapshot(root)
    with pytest.raises(QueueError, match="require a retained Slurm store"):
        storage_upgrade(request, action="apply")
    assert _snapshot(root) == before
    assert not (_agent_root(agent) / "slurm.sqlite").exists()


def test_https_inspection_never_qualifies_remote_authority(root, monkeypatch):
    from loom.queue import deployment
    request, coordinator, _, _, _ = _cohort(root)
    item = json.loads(request.read_bytes())["roles"][0]
    for side in ("source", "target"):
        path = Path(item[side + "_config"])
        payload = json.loads(path.read_bytes())
        payload["authority"] = {
            "kind": "https", "url": "https://authority.example:9443", "service_id": "authority",
            "workspace_id": "workspace", "tls": {"ca": "ca.crt", "certificate": "client.crt", "private_key": "client.key"},
        }
        _write_protected(path, payload)
    # Retain the native projection for this independent remote-authority fixture.
    assert coordinator.daemon.deployment_root is not None
    binding_path = coordinator.daemon.deployment_root / "deployment-binding.json"
    binding = json.loads(binding_path.read_bytes())
    _, _, source = deployment._read_coordinator_declaration(item["source_config"])
    binding["immutable_fingerprint"] = deployment._canonical_fingerprint({
        "coordinator": deployment._coordinator_immutable_projection(source), "local_agent": None,
    })
    _write_protected(binding_path, binding)

    def forbidden(*args, **kwargs):
        raise AssertionError("inspection must not qualify HTTPS readiness")

    monkeypatch.setattr("loom.pipeline.stores.coordinator_authority.https_coordinator_authority_factory", forbidden)
    before = _snapshot(root)
    assert storage_upgrade(request)["state"] == "eligible"
    assert _snapshot(root) == before


def test_workspace_inventory(root):
    from loom.queue._remote_stage_execution import _ResidentAssignmentWorkspace
    request, _, agent, _, target = _cohort(root, kind="resident")
    # Interrupted allocation before request publication leaves a native empty
    # workspace, which still needs its selected policy when reopened later.
    workspace = _ResidentAssignmentWorkspace(_agent_root(agent), "empty")
    storage_upgrade(request, action="apply")
    reopened = _ResidentAssignmentWorkspace(_agent_root(target), "empty",
        sqlite_policy=target.client.sqlite_policy, durable_files="strict", _allow_initialize=False)
    assert reopened.root == workspace.root
    assert reopened.durable_files == "strict"
    assert storage_upgrade(request, action="restore")["state"] == "restored"
    restored = _ResidentAssignmentWorkspace(_agent_root(agent), "empty", _allow_initialize=False)
    assert restored.durable_files == "best_effort"


def test_pending_work_and_missing_store(root):
    request, _, agent, _, _ = _cohort(root)
    database = _agent_root(agent) / "control.sqlite"
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("INSERT INTO agent_controls_local VALUES ('pending','{}',NULL,'{}',0)")
    with pytest.raises(QueueError, match="settled"):
        storage_upgrade(request, action="apply")
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("DELETE FROM agent_controls_local")
    (_agent_root(agent) / "slurm.sqlite").unlink()
    with pytest.raises(QueueError, match="require a retained Slurm store"):
        storage_upgrade(request, action="apply")
    assert not (_agent_root(agent) / "slurm.sqlite").exists()
    assert not (root / "snapshots").exists()


def test_guard_default_and_malformed(root):
    require_storage_upgrade_ready(root)
    _write_protected(root / GUARD_NAME, {"version": 5})
    with pytest.raises(QueueError):
        require_storage_upgrade_ready(root)


def test_released_history(root):
    from loom.queue.slurm_ready_stage import _upgrade_released_schema, SQLiteSlurmStageAssignments
    from tests.unit.loom.queue.test_slurm_admission import ReservationFixture
    fixture = ReservationFixture(root, schema_version=3)
    SlurmSubmissionProjection(fixture.path, _allow_initialize=True, schema_version=3)
    assignment, arguments = fixture.candidate("history", 2)
    arguments.update(requested_gpu_count=None, max_reserved_gpus=None)
    fixture.store.reserve(assignment, **arguments)
    with closing(sqlite3.connect(fixture.path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(QueueError, match="released"):
            _upgrade_released_schema(conn)
        conn.rollback()
        assert conn.execute("PRAGMA user_version").fetchone() == (3,)
    fixture.store.mark_contained_cancelled("history")
    fixture.store.release("history")
    with closing(sqlite3.connect(fixture.path)) as conn:
        conn.row_factory = sqlite3.Row
        before = dict(conn.execute("SELECT * FROM slurm_stage_assignments").fetchone())
        conn.execute("BEGIN IMMEDIATE")
        _upgrade_released_schema(conn)
        conn.commit()
        after = dict(conn.execute("SELECT * FROM slurm_stage_assignments").fetchone())
        assert {key: after[key] for key in before} == before
        assert after["requested_gpu_count"] is None
        assert after["capability_delivery_kind"] is None
        assert after["capability_expires_at"] is None
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE slurm_stage_assignments SET state='running'")
    SlurmSubmissionProjection(fixture.path, schema_version=4)._open_existing()
    store = SQLiteSlurmStageAssignments(fixture.path, fixture.transfers, schema_version=4, _allow_initialize=False)
    store._open_existing()
    assert store.reserved_gpu_count() == 0


def test_restore_interruption(root, monkeypatch):
    request, coordinator, agent, target, _ = _cohort(root)
    storage_upgrade(request, action="apply")
    copy = upgrade_module._copy_database
    fired = False

    def interrupted(source, destination, *, mode):
        nonlocal fired
        copy(source, destination, mode=mode)
        if destination == _agent_root(agent) / "control.sqlite" and not fired:
            fired = True
            raise OSError("restore acknowledgement lost")

    monkeypatch.setattr(upgrade_module, "_copy_database", interrupted)
    with pytest.raises(OSError, match="restore acknowledgement"):
        storage_upgrade(request, action="restore")
    with pytest.raises(QueueError, match="incomplete"):
        LocalDaemon(target.daemon).start()
    assert storage_upgrade(request, action="restore")["state"] == "restored"
    _validate_deployment_binding(coordinator.daemon)


def test_snapshot_interruption(root, monkeypatch):
    request, coordinator, _, _, _ = _cohort(root)
    prepare = upgrade_module._prepare_database
    facts = upgrade_module._db_facts(coordinator.daemon.control_database)
    fired = False

    def interrupted(*args):
        nonlocal fired
        prepare(*args)
        if not fired:
            fired = True
            raise OSError("snapshot interrupted")

    monkeypatch.setattr(upgrade_module, "_prepare_database", interrupted)
    with pytest.raises(OSError, match="snapshot interrupted"):
        storage_upgrade(request, action="apply")
    assert not (coordinator.daemon.coordinator_root / GUARD_NAME).exists()
    assert upgrade_module._db_facts(coordinator.daemon.control_database) == facts
    assert storage_upgrade(request, action="resume")["state"] == "ready"


def test_new_upgrade_prevents_old_restore(root):
    request, _, _, _, _ = _cohort(root)
    storage_upgrade(request, action="apply")
    value = json.loads(request.read_bytes())
    value.update(operation_id="conversion-2", snapshot_root=str(root / "second-snapshot"))
    for role in value["roles"]:
        role["source_config"] = role["target_config"]
        path = Path(role["source_config"])
        payload = json.loads(path.read_bytes())
        payload["storage"]["sqlite"]["journal_mode"] = "wal"
        if role["role"] == "coordinator":
            payload["slurm_admission"]["max_reserved_gpus"] = 9
        role["target_config"] = str(_write_protected(path.with_name("second-target.yaml"), payload))
    second = _write_protected(root / "second-request.json", value)
    storage_upgrade(second, action="apply")
    for owner in storage_upgrade(second)["owners"]:
        assert all(upgrade_module._db_facts(Path(name))[1] == "wal" for name in owner["databases"])
    before = _snapshot(root)
    with pytest.raises(QueueError, match="different operation"):
        storage_upgrade(request, action="restore")
    assert _snapshot(root) == before


def test_cli_inspection(root):
    from loom.cli.main import main
    request, _, _, _, _ = _cohort(root)
    before = _snapshot(root)
    stdout, stderr = io.StringIO(), io.StringIO()
    assert main(["queue", "storage-upgrade", "inspect", "--request", str(request), "--format", "json"],
                stdout=stdout, stderr=stderr) == 0, stderr.getvalue()
    assert json.loads(stdout.getvalue())["result"]["state"] == "eligible"
    assert _snapshot(root) == before


def test_availability_startup_guard(root, monkeypatch):
    from loom.deployment import DeploymentSelection, LocalRole, _bind
    from tests.integration.queue.test_preparation_operations import _request
    request, coordinator, _, target, _ = _cohort(root)
    selection = DeploymentSelection(
        root / "selection.json", None, LocalRole(target.source_path, "persistent", None), None,
        root / "availability.json", _request().source, "python", 10, None,
    )
    copy = upgrade_module._copy_database
    fired = False

    def interrupt(source, destination, *, mode):
        nonlocal fired
        copy(source, destination, mode=mode)
        if destination == coordinator.daemon.control_database and not fired:
            fired = True
            raise OSError("interrupted")

    monkeypatch.setattr(upgrade_module, "_copy_database", interrupt)
    with pytest.raises(OSError):
        storage_upgrade(request, action="apply")
    before = _snapshot(root / "c")
    with pytest.raises(QueueError, match="incomplete"):
        _bind(selection, "held", time.monotonic() + 10)
    assert _snapshot(root / "c") == before
    assert selection.binding is not None
    assert not selection.binding.exists()
    storage_upgrade(request, action="resume")
    _bind(selection, "ready", time.monotonic() + 10)
    with pytest.raises(QueueError, match="after a target owner entered"):
        storage_upgrade(request, action="restore")


def test_activation_sync_failure(root, monkeypatch):
    import loom.pipeline.stores.atomic as atomic
    request, _, _, _, agent = _cohort(root)
    storage_upgrade(request, action="apply")
    sync = atomic._fsync_path_strict
    failed = False

    def fail_receipt(path):
        nonlocal failed
        if path == root / "snapshots" and tuple(path.glob("entered-*.json")) and not failed:
            failed = True
            raise OSError("activation sync failed")
        return sync(path)

    monkeypatch.setattr(atomic, "_fsync_path_strict", fail_receipt)
    options: dict[str, Any] = dict(expected_configuration_fingerprint=agent.immutable_fingerprint,
                   expected_active_configuration_fingerprint=agent.active_fingerprint,
                   sqlite_policy=agent.client.sqlite_policy)
    before = upgrade_module._db_facts(_agent_root(agent) / "control.sqlite")
    with pytest.raises(QueueError, match="upgrade evidence is unavailable"):
        _RemoteAgentJournal(_agent_root(agent), **options)
    assert upgrade_module._db_facts(_agent_root(agent) / "control.sqlite") == before
    with _acquire_lock(_agent_root(agent)):
        pass  # Failed activation released ownership.
    journal = _RemoteAgentJournal(_agent_root(agent), **options)
    journal.close()
    assert storage_upgrade(request)["entered"] is True


@pytest.mark.parametrize("wrong_binding", [False, True])
def test_bootstrap_upgrade_remaps_only_existing_exact_profile_authorization(root, wrong_binding):
    request, _, _, new_c, _ = _cohort(root, replayable_start=True, bootstrap_upgrade=True)
    if wrong_binding:
        declaration = json.loads(request.read_text())["roles"][0]
        target = Path(declaration["target_config"])
        payload = json.loads(target.read_text())
        payload["agent_policy"]["agents"][0]["external_slurm_profiles"][0][1] = "unrelated-digest"
        _write_protected(target, payload)
        before = _snapshot(root)
        with pytest.raises(QueueError, match="other declarations must match"):
            storage_upgrade(request)
        assert _snapshot(root) == before
    else:
        assert storage_upgrade(request)["state"] == "eligible"
        assert storage_upgrade(request, action="apply")["state"] == "ready"
        _validate_deployment_binding(new_c.daemon)
