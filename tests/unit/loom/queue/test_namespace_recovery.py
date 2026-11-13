from dataclasses import replace
import json
import sqlite3
import subprocess
import sys

import pytest

from loom.queue._namespace_recovery import ProcessIdentity, _PinnedProcess, _facts, _receipt, _selection, _recover
from loom.queue._agent_process_supervisor import AgentProcessSupervisor, _host_boot_evidence
from loom.queue.errors import QueueConflictError
from tests.unit.loom.queue.test_agent_process_supervisor import _profile, _launch


def test_stale_birth_ticks_leave_real_process_running():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        with pytest.raises(QueueConflictError, match="identity changed"):
            _PinnedProcess(ProcessIdentity(child.pid, 1))
        assert child.poll() is None
        pinned = _PinnedProcess(ProcessIdentity(child.pid, _facts(child.pid)["start_ticks"]))
        try:
            pinned.stop()
            assert _facts(child.pid)["state"] == "T"
        finally:
            pinned.close()
        # Cleanup of a failed/preflight operation resumes the original owner.
        assert child.poll() is None
    finally:
        child.kill()
        child.wait()


def test_interrupted_recovery_never_becomes_containment():
    with sqlite3.connect(":memory:") as conn:
        assert _receipt(conn, "op", "intent") is None
        conn.execute("CREATE TABLE namespace_recoveries(operation_id TEXT, intent TEXT, result TEXT)")
        conn.execute("INSERT INTO namespace_recoveries VALUES ('op', 'intent', NULL)")
        with pytest.raises(QueueConflictError, match="interrupted"):
            _receipt(conn, "op", "intent")
        with pytest.raises(QueueConflictError, match="conflicts"):
            _receipt(conn, "op", "other")


def test_changed_boot_refuses_before_opening_processes(tmp_path):
    with pytest.raises(QueueConflictError, match="boot changed"):
        _recover(tmp_path, "agent", operation_id="op", assignment_id="assignment", boot_id="old",
                 supervisor=ProcessIdentity(1, 1), launcher=ProcessIdentity(2, 1), namespace=ProcessIdentity(3, 1))


def test_another_unresolved_launch_refuses_targeted_recovery(tmp_path):
    profile = replace(_profile(), container={
        "kind": "apptainer", "container": {"image": {"reference": "/fixture.sif"}},
        "options": {"command": "/usr/bin/singularity"},
        "python_executable": "/opt/python", "daemon_endpoint": None,
    })
    owner = AgentProcessSupervisor.initialize(tmp_path, agent_id="agent-A", profiles=(profile,))
    launch = replace(_launch(owner, tmp_path / "work"), profile=profile)
    from loom.queue._agent_process_supervisor import _launch_json
    with owner._connect() as conn:
        for item in (launch, replace(launch, assignment_id="peer", launch_operation_id="peer-op")):
            conn.execute("INSERT INTO launches(operation_id,digest,launch_json,state,revision,pid) VALUES (?,?,?,'unknown',1,123)",
                         (item.launch_operation_id, item.spec_digest, _launch_json(item)))
        with pytest.raises(QueueConflictError, match="exactly one"):
            _selection(conn, launch.assignment_id, owner.supervisor_id, owner.continuity_epoch, owner.root, _host_boot_evidence())
        assert {r[0] for r in conn.execute("SELECT state FROM launches")} == {"unknown"}


def test_cli_namespace_recovery_passes_exact_process_identity(tmp_path, monkeypatch):
    import io
    from types import SimpleNamespace
    from loom.cli.main import main
    from loom.queue import _namespace_recovery
    calls = []
    monkeypatch.setattr("loom.queue.deployment.load_outbound_agent_service_config", lambda *a, **kw: SimpleNamespace(client="config"))
    def recover(config, **kwargs):
        calls.append((config, kwargs))
        return {"state": "contained"}
    monkeypatch.setattr(_namespace_recovery, "recover_namespace", recover)
    arguments = ["queue", "agent-recover-namespace", str(tmp_path / "agent.yaml"),
                 "--operation-id", "recovery", "--assignment-id", "assignment", "--boot-id", "boot", "--format", "json"]
    for role, pid in (("supervisor", 11), ("launcher", 12), ("namespace", 13)):
        arguments.extend([f"--{role}-pid", str(pid), f"--{role}-start-ticks", "123"])
    out, err = io.StringIO(), io.StringIO()
    assert main(arguments, stdout=out, stderr=err) == 0, err.getvalue()
    assert calls[0][1]["launcher"] == ProcessIdentity(12, 123)
    assert calls[0][1]["boot_id"] == "boot"
    assert json.loads(out.getvalue())["result"]["state"] == "contained"


def test_live_agent_lock_refuses_before_process_inspection(tmp_path):
    import io
    from loom.cli.main import main
    from loom.queue._agent_session_journal import _RemoteAgentJournal
    from loom.queue._namespace_recovery import recover_namespace
    from loom.queue.deployment import load_outbound_agent_service_config
    from loom.queue.errors import QueueServiceError
    from tests.unit.loom.cli.test_queue import _outbound_agent_service_config

    path = _outbound_agent_service_config(tmp_path)
    assert main(["queue", "agent-init", str(path)], stdout=io.StringIO(), stderr=io.StringIO()) == 0
    service = load_outbound_agent_service_config(path)
    held = _RemoteAgentJournal(service.client.agent_root)
    try:
        with pytest.raises(QueueServiceError, match="already locked"):
            recover_namespace(service.client, operation_id="op", assignment_id="assignment", boot_id="boot",
                              supervisor=ProcessIdentity(1, 1), launcher=ProcessIdentity(2, 1), namespace=ProcessIdentity(3, 1))
    finally:
        held.close()
