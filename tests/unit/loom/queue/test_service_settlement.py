"""Read-only settlement distinguishes absent capabilities from missing stores."""

from contextlib import closing
import json
from pathlib import Path
import socket
import sqlite3
import sys

import pytest

from loom._sqlite_policy import SQLitePolicy
from loom.pipeline.executors.slurm.commands import FakeSlurmCommandRunner
from loom.queue import LocalDaemon, LocalDaemonConfig
from loom.queue._agent_slurm import AgentSlurmJobs
from loom.queue._remote_stage_execution import ResidentExecutionProfile, ResidentProfileDescriptor
from loom.queue._slurm_admission import SlurmAdmissionPolicy
from loom.queue._slurm_terminal_recovery import SlurmTerminalRecoveryPolicy
from loom.queue._storage_policy import StoragePolicy
from loom.queue.agent_session_transport import (
    AgentTlsClientConfig, LocalDaemonAgentHttpClient, _read_remote_agent_root_id,
)
from loom.queue.service_upgrade import inspect_service_settlement
from tests.unit.loom.queue.test_agent_slurm import _profile, _task
from tests.unit.loom.queue.test_agent_slurm_storage import drive_until


def _agent(root, *, kind="slurm", rollback=False):
    root.mkdir()
    profile = _profile(FakeSlurmCommandRunner(), root)
    resident = ResidentExecutionProfile(
        ResidentProfileDescriptor("python", "1", "project", "environment", "executor"),
        root, Path(sys.executable), cpu_capacity=1,
    )
    config = AgentTlsClientConfig(
        "https://localhost", root / "ca.crt", root / "agent.crt", root / "agent.key",
        agent_root=root / "agent",
        resident_profiles=() if kind == "slurm" else (resident,),
        slurm_profiles=() if kind == "resident" else (profile,),
        storage=StoragePolicy(socket.gethostname(), SQLitePolicy("delete", "extra")) if rollback else None,
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(config)
    return config, profile, _read_remote_agent_root_id(config.agent_root)


def _snapshot(root):
    return {
        str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*") if path.is_file()
    }


def _inspect(config, root_id):
    before = _snapshot(config.agent_root)
    value = inspect_service_settlement(config.agent_root, expected_root_id=root_id)
    assert _snapshot(config.agent_root) == before
    return value


@pytest.mark.parametrize("kind", ["slurm", "resident", "mixed"])
@pytest.mark.parametrize("rollback", [False, True])
def test_fresh_agent_settlement_uses_retained_execution_inventory(tmp_path, kind, rollback):
    config, _, identity = _agent(tmp_path / "case", kind=kind, rollback=rollback)
    observation = _inspect(config, identity)
    assert observation.availability == "available", observation.to_dict()
    assert observation.to_dict()["value"] == {"settled": True, "wait_reasons": []}
    assert (config.agent_root / "supervisor").exists() is (kind != "slurm")


@pytest.mark.parametrize(("kind", "missing"), [
    ("slurm", "slurm.sqlite"), ("slurm", "journal.sqlite"),
    ("resident", "supervisor/supervisor.sqlite"), ("mixed", "slurm.sqlite"),
])
def test_missing_required_store_refuses_without_recreation(tmp_path, kind, missing):
    config, _, identity = _agent(tmp_path / "case", kind=kind)
    (config.agent_root / missing).unlink()
    observation = _inspect(config, identity)
    assert observation.availability == "unavailable"
    assert observation.reason == "settlement_evidence_unavailable"
    assert not (config.agent_root / missing).exists()


@pytest.mark.parametrize("kind", ["resident", "slurm"])
def test_legacy_roots_do_not_infer_missing_supervisor_is_intentional(tmp_path, kind):
    config, _, identity = _agent(tmp_path / "case", kind=kind)
    with closing(sqlite3.connect(config.agent_root / "control.sqlite")) as conn, conn:
        conn.execute("DELETE FROM root_metadata WHERE key = 'execution_store_requirements'")
    observation = _inspect(config, identity)
    assert observation.availability == ("available" if kind == "resident" else "unavailable")
    if kind == "resident":
        assert observation.value["settled"] is True


@pytest.mark.parametrize("failure", ["before_submit", "provider_revoke", "release_ack"])
def test_agent_settlement_waits_for_full_slurm_release(tmp_path, monkeypatch, failure):
    config, profile, identity = _agent(tmp_path / "case", rollback=True)
    agent = AgentSlurmJobs(config.agent_root, (profile,), sqlite_policy=config.sqlite_policy)
    task = _task(profile)
    task["assignment"]["agent_root_id"] = identity
    failing = True

    def acknowledge(evidence):
        if failure == "release_ack" and failing and evidence["provider_released"]:
            raise OSError("lost final acknowledgement")
        return {"sequence": evidence["sequence"], "cancel_requested": True}

    provider_class = type(profile.job_private_file_provider)
    revoke = provider_class.revoke

    def fail_revoke(self, prepared):
        if failure == "provider_revoke" and failing:
            raise OSError("interrupted provider revoke")
        return revoke(self, prepared)

    monkeypatch.setattr(provider_class, "revoke", fail_revoke)
    if failure == "before_submit":
        agent.step(task, lambda evidence: {"sequence": evidence["sequence"]}, allow_submission=False)
    else:
        with pytest.raises(OSError):
            agent.step(task, acknowledge)
    pending = _inspect(config, identity)
    assert pending.availability == "available", pending.to_dict()
    assert pending.value["settled"] is False
    assert "slurm_submission_or_release" in pending.value["wait_reasons"]
    failing = False
    agent.close()
    agent = AgentSlurmJobs(config.agent_root, (profile,), sqlite_policy=config.sqlite_policy)
    try:
        drive_until(
            lambda: agent.step(task, acknowledge),
            lambda: _inspect(config, identity).value.get("settled") is True,
        )
    finally:
        agent.close()
    settled = _inspect(config, identity)
    assert settled.value["settled"] is True, settled.to_dict()
    assert not any(call[0] == "sbatch" for call in profile.runner.calls)


@pytest.mark.parametrize(("database", "statement", "reason"), [
    ("journal.sqlite", "INSERT INTO diagnostic_probes VALUES ('probe','agent','{}','contained')", "diagnostic_release"),
    ("control.sqlite", "INSERT INTO agent_controls_local VALUES ('control','{}',NULL,'{}',0)", "local_control_settlement"),
])
def test_retained_cleanup_and_acknowledgements_prevent_settlement(tmp_path, database, statement, reason):
    config, _, identity = _agent(tmp_path / "case")
    # These retained states model interruptions before provider/evidence ack.
    with closing(sqlite3.connect(config.agent_root / database)) as conn, conn:
        conn.execute(statement)
    observation = _inspect(config, identity)
    assert observation.availability == "available"
    assert observation.value["settled"] is False
    assert reason in observation.value["wait_reasons"]


def test_local_assignment_and_event_are_owned_until_acknowledged(tmp_path):
    from loom.queue._managed_local import ManagedAssignment, SQLiteAgentJournal

    config, _, identity = _agent(tmp_path / "case", kind="resident")
    journal = SQLiteAgentJournal(config.agent_root / "journal.sqlite", _allow_initialize=False)
    assignment = ManagedAssignment(
        "assignment", "file:///run", "work", "stage", 1, "attempt", identity,
        "session", "offer", "claim",
    )
    journal.persist_request(assignment, {})
    assert "local_execution_release" in _inspect(config, identity).value["wait_reasons"]
    journal.decline_before_prepare(assignment.assignment_id)
    sequence = journal.append_event(assignment.assignment_id, "decline", {"state": "declined"})
    assert "local_execution_evidence" in _inspect(config, identity).value["wait_reasons"]
    journal.acknowledge(assignment.assignment_id, sequence)
    assert _inspect(config, identity).value["settled"] is True


@pytest.mark.parametrize(("state", "pending", "error"), [
    ("starting", 0, None), ("contained", 1, None), ("contained", 0, "cleanup unavailable"),
])
def test_supervisor_terminal_state_does_not_skip_temporary_cleanup(tmp_path, state, pending, error):
    from loom.queue._agent_process_supervisor import ResidentWorkerLaunch, _launch_value

    config, _, identity = _agent(tmp_path / "case", kind="resident")
    database = config.agent_root / "supervisor/supervisor.sqlite"
    with closing(sqlite3.connect(database)) as conn, conn:
        metadata = dict(conn.execute("SELECT key, value FROM metadata"))
        launch = ResidentWorkerLaunch(
            supervisor_id=metadata["supervisor_id"], continuity_epoch=metadata["continuity_epoch"],
            agent_id=identity, session_id="session", assignment_id="assignment",
            process_execution_id="process", execution_fence="fence", launch_operation_id="launch",
            bundle_digest="a" * 64, workspace_root=tmp_path / "workspace",
            profile=config.resident_profiles[0].launch_profile, environment={},
        )
        # Retained boundaries from before spawn or after process containment;
        # no process is required to test a read-only cleanup decision.
        conn.execute(
            "INSERT INTO launches(operation_id,digest,launch_json,state,revision,"
            "temporary_storage_pending,temporary_storage_error) VALUES (?,?,?,?,1,?,?)",
            (launch.launch_operation_id, launch.spec_digest, json.dumps(_launch_value(launch)), state, pending, error),
        )
    assert "supervisor_containment" in _inspect(config, identity).value["wait_reasons"]
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("UPDATE launches SET state='contained',temporary_storage_pending=0,temporary_storage_error=NULL")
    assert _inspect(config, identity).value["settled"] is True


def test_malformed_retained_inventory_does_not_skip_required_stores(tmp_path):
    config, _, identity = _agent(tmp_path / "case")
    with closing(sqlite3.connect(config.agent_root / "control.sqlite")) as conn, conn:
        conn.execute(
            "UPDATE root_metadata SET value=? WHERE key='execution_store_requirements'",
            (json.dumps({"version": 1, "supervisor": False}),),
        )
    assert _inspect(config, identity).availability == "unavailable"


@pytest.mark.parametrize("code", ["never_started", "terminal"])
def test_acknowledged_assignment_control_needs_no_optional_containment_payload(tmp_path, code):
    from loom.queue._agent_session_journal import _RemoteAgentJournal
    from loom.queue.agent_sessions import AgentAssignmentControl

    config, _, identity = _agent(tmp_path / "case", kind="resident")
    control = AgentAssignmentControl("cancel", "session", "assignment", None, None)
    with closing(_RemoteAgentJournal(config.agent_root)) as journal:
        assert journal.prepare_assignment_control(control) is None
        # A premature acknowledgement cannot resolve an incomplete result.
        journal.acknowledge_assignment_control(control.operation_id)
        assert "local_control_settlement" in _inspect(config, identity).value["wait_reasons"]
        journal.record_assignment_control_result(control, code, None)
        assert "local_control_settlement" in _inspect(config, identity).value["wait_reasons"]
        journal.acknowledge_assignment_control(control.operation_id)
        observation = _inspect(config, identity)
        assert observation.availability == "available", observation.to_dict()
        assert observation.value["settled"] is True


@pytest.mark.parametrize("version", [3, 4, 7])
def test_coordinator_settlement_validates_execution_owner_without_mutation(tmp_path, version):
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator", agent_root=None,
        resident_worker_launch_profile=None, cpu_capacity=0,
        run_store_root=tmp_path / "runs",
        slurm_admission=SlurmAdmissionPolicy(8) if version == 4 else None,
        slurm_terminal_recovery=SlurmTerminalRecoveryPolicy() if version == 7 else None,
    )
    LocalDaemon.initialize(config)
    with closing(sqlite3.connect(config.control_database)) as conn:
        identity = conn.execute("SELECT value FROM root_metadata WHERE key='stable_id'").fetchone()[0]
    before = _snapshot(config.coordinator_root)
    observation = inspect_service_settlement(config.coordinator_root, expected_root_id=identity)
    assert observation.availability == "available", observation.to_dict()
    assert observation.value["settled"] is True
    assert _snapshot(config.coordinator_root) == before
    config.execution_database.unlink()
    before = _snapshot(config.coordinator_root)
    assert inspect_service_settlement(config.coordinator_root, expected_root_id=identity).availability == "unavailable"
    assert _snapshot(config.coordinator_root) == before


@pytest.mark.parametrize("condition", ["reserved", "unknown_schema", "missing_column"])
def test_schema_seven_settlement_refuses_unreleased_or_incompatible_state(tmp_path, condition):
    from tests.unit.loom.queue.test_slurm_admission import ReservationFixture

    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator", agent_root=None,
        resident_worker_launch_profile=None, cpu_capacity=0,
        run_store_root=tmp_path / "runs",
        slurm_terminal_recovery=SlurmTerminalRecoveryPolicy(),
    )
    LocalDaemon.initialize(config)
    with closing(sqlite3.connect(config.control_database)) as conn:
        identity = conn.execute("SELECT value FROM root_metadata WHERE key='stable_id'").fetchone()[0]
    if condition == "reserved":
        fixture = ReservationFixture(config.coordinator_root, schema_version=7)
        assignment, arguments = fixture.candidate("unreleased", 0)
        fixture.store.reserve(assignment, **arguments)
    else:
        with closing(sqlite3.connect(config.execution_database)) as conn:
            conn.execute("PRAGMA user_version=99" if condition == "unknown_schema" else
                         "ALTER TABLE slurm_stage_assignments DROP COLUMN terminal_observation_json")
            conn.commit()
    before = _snapshot(config.coordinator_root)
    observation = inspect_service_settlement(config.coordinator_root, expected_root_id=identity)
    assert _snapshot(config.coordinator_root) == before
    if condition == "reserved":
        assert observation.availability == "available", observation.to_dict()
        assert observation.value["settled"] is False
        assert observation.value["wait_reasons"] == ["slurm_assignment_or_release"]
    else:
        assert observation.availability == "unavailable"
        assert observation.reason == "settlement_evidence_unavailable"
