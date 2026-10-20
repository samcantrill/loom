"""Delayed readiness is one retained launch, not a repeated startup request."""
from copy import deepcopy
import json
from pathlib import Path
from subprocess import CompletedProcess
from types import SimpleNamespace
import tempfile
import io

import pytest

from loom.fleet import _host, _services, _startup, _upgrade_host, _workload_host
from loom.fleet import ssh_operations, upgrades
from loom.queue.errors import QueueConflictError


@pytest.fixture
def startup(tmp_path, monkeypatch):
    temporary = tempfile.TemporaryDirectory(prefix="fleet-start-")
    request = {"admin": str(Path(temporary.name) / "admin"), "root": str(tmp_path / "root"),
               "name": "worker", "request_id": "start-operation", "expected_root_id": "root-id",
               "config": str(tmp_path / "agent.json"), "coordinator_id": "coordinator",
               "release": {"descriptor_sha256": "runtime"}}
    Path(request["admin"]).mkdir(mode=0o700)
    now = [100.0]
    monkeypatch.setattr(_startup.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(_startup.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    monkeypatch.setattr(_startup, "process_identity", lambda pid: {"pid": int(pid), "started": "42"})
    monkeypatch.setattr(_host, "payload", lambda _: {})
    monkeypatch.setattr(_host, "environment", lambda _: None)
    state = SimpleNamespace(ready_at=125.0, present=False, pid=47, token=None,
                            root="root-id", launches=0, failed=False, invocation="invocation-1")

    def owner(_):
        return {"owner": "root-id", "value": {
            "ownership": "live" if now[0] >= state.ready_at and state.present else "unproven",
            "expected_process": state.pid,
        }}
    monkeypatch.setattr(_host, "owner", owner)
    yield request, state, now
    temporary.cleanup()


def tmux_backend(monkeypatch, state):
    def run(argv, **kwargs):
        if "new-session" in argv:
            state.launches += 1
            state.present = True
            state.token = argv[-1]
            return CompletedProcess(argv, 0)
        assert "list-panes" in argv
        if not state.present:
            return CompletedProcess(argv, 1, "", "")
        return CompletedProcess(argv, 0, f"{state.root}\t{state.token}\t{state.pid}\n", "")
    monkeypatch.setattr(_host.subprocess, "run", run)


def test_tmux_slow_start_reopens_same_attempt_without_reset_or_duplicate(startup, monkeypatch):
    request, state, now = startup
    tmux_backend(monkeypatch, state)
    with pytest.raises(_startup.ServiceStarting, match="service_starting"):
        _host.start(request)
    path = _startup.startup_path(request)
    deadline = _host.read(path)["deadline"]
    assert now[0] >= 120 and state.launches == 1
    now[0] = 126
    assert _host.start(deepcopy(request))["native_owner"]["value"]["ownership"] == "live"
    assert _host.read(path)["deadline"] == deadline and _host.read(path)["ready"]
    assert state.launches == 1


@pytest.mark.parametrize("failure", ["deadline", "exited", "owner", "process"])
def test_tmux_pending_failure_never_launches_a_successor(startup, monkeypatch, failure):
    request, state, now = startup
    tmux_backend(monkeypatch, state)
    state.ready_at = 1000
    with pytest.raises(_startup.ServiceStarting):
        _host.start(request)
    if failure == "deadline":
        now[0] = 281
        message = "service_readiness_timeout"
    elif failure == "exited":
        state.present = False
        message = "service_start_failed"
    elif failure == "owner":
        state.root = "another-root"
        message = "owner differs"
    else:
        state.pid = 48
        message = "process ownership changed"
    with pytest.raises(QueueConflictError, match=message):
        _host.start(request)
    assert state.launches == 1


def systemd_backend(monkeypatch, state, now):
    monkeypatch.setattr(_services, "prerequisites", lambda: None)
    def systemctl(*args):
        if args[0] == "start":
            assert args[1] == "--no-block"
            state.present = True
            state.launches += 1
        return ""
    monkeypatch.setattr(_services, "systemctl", systemctl)
    monkeypatch.setattr(_services, "startup_status", lambda _: {
        "ActiveState": "failed" if state.failed else "active" if now[0] >= state.ready_at else "activating",
        "MainPID": str(state.pid) if now[0] >= state.ready_at else "0",
        "InvocationID": state.invocation, "Job": "0 /" if state.failed else "1 /job",
    })


def test_systemd_slow_start_retains_invocation_and_deadline(startup, monkeypatch):
    request, state, now = startup
    request["service_manager"] = "systemd-user"
    systemd_backend(monkeypatch, state, now)
    with pytest.raises(_startup.ServiceStarting):
        _host.start(request)
    deadline = _host.read(_startup.startup_path(request))["deadline"]
    now[0] = 126
    assert _host.start(request)["boot_start"]
    assert state.launches == 1 and _host.read(_startup.startup_path(request))["deadline"] == deadline


@pytest.mark.parametrize("failure", ["failed", "invocation", "deadline"])
def test_systemd_pending_launch_failure_is_explicit(startup, monkeypatch, failure):
    request, state, now = startup
    request["service_manager"] = "systemd-user"
    state.ready_at = 1000
    systemd_backend(monkeypatch, state, now)
    with pytest.raises(_startup.ServiceStarting):
        _host.start(request)
    if failure == "failed":
        state.failed = True
        message = "service_start_failed"
    elif failure == "invocation":
        state.invocation = "another-invocation"
        message = "backend ownership changed"
    else:
        now[0] = 281
        message = "service_readiness_timeout"
    with pytest.raises(QueueConflictError, match=message):
        _host.start(request)
    assert state.launches == 1


def test_pending_host_reply_is_waiting_not_transport_failure(monkeypatch):
    from loom.fleet import _ssh_bootstrap
    native_reply = {"host_error": {"code": "ServiceStarting", "reason": "service_starting"}}
    with pytest.raises(_ssh_bootstrap.ServiceStarting) as host_error:
        _ssh_bootstrap.host_result(CompletedProcess([], 1, json.dumps(native_reply), ""))
    reply = {"ok": False, "code": type(host_error.value).__name__, "reason": str(host_error.value)}
    monkeypatch.setattr(ssh_operations.subprocess, "run", lambda *a, **k:
                        CompletedProcess(a, 1, json.dumps(reply).encode(), b""))
    with pytest.raises(ssh_operations.SshStarting) as error:
        ssh_operations.ssh("worker", {})
    assert upgrades._reason_code(error.value) == "acknowledgement_pending"


def test_pending_native_host_attempt_does_not_publish_completion(startup, monkeypatch):
    request, _, _ = startup
    request["action"] = "start"
    monkeypatch.setattr(_host.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(request).encode())))
    monkeypatch.setattr(_host, "execute", lambda *a: (_ for _ in ()).throw(_startup.ServiceStarting()))
    with pytest.raises(_startup.ServiceStarting):
        _host.main()
    directory = Path(request["admin"]) / "operations" / request["request_id"]
    assert (directory / "intent.json").exists() and (directory / "dispatched.json").exists()
    assert not (directory / "receipt.json").exists()


def test_runtime_replacement_continues_start_without_repeating_activation(startup, monkeypatch):
    request, _, _ = startup
    request["source_release"] = {"descriptor_sha256": "previous"}
    admin = Path(request["admin"])
    _host.atomic(admin / "active.json", request["release"])
    _host.atomic(admin / "service.json", request)
    monkeypatch.setattr(_host, "start", lambda _: (_ for _ in ()).throw(_startup.ServiceStarting()))
    monkeypatch.setattr(_upgrade_host, "inspect", lambda _: pytest.fail("activation repeated"))
    with pytest.raises(_startup.ServiceStarting):
        _upgrade_host.replace(request)


def test_launch_to_readiness_timing_survives_continuation_without_relaunch(startup, monkeypatch):
    from loom.fleet import _timing
    request, state, now = startup
    state.ready_at = 150
    tmux_backend(monkeypatch, state)
    with _timing.recording() as trace:
        with pytest.raises(_startup.ServiceStarting):
            _host.start(request)
        assert not any(row["action"] == "launch_to_readiness" for row in trace.records)
        now[0] = 150
        _host.start(request)
        _host.start(request)
    rows = [row for row in trace.records if row["action"] == "launch_to_readiness"]
    assert len(rows) == 1 and rows[0]["elapsed_seconds"] == 50
    assert state.launches == 1


def test_workload_pending_start_recovers_and_qualifies_once(startup, monkeypatch):
    from loom.queue import _profile_promotion
    request, state, now = startup
    request["promotion_id"] = "promotion"
    state.ready_at = 1000
    _host.atomic(Path(request["admin"]) / "service.json", request)
    monkeypatch.setattr(_workload_host, "owner", _host.owner)
    monkeypatch.setattr(_workload_host, "payload", lambda _: {})
    calls = []
    monkeypatch.setattr(_workload_host, "load_outbound_agent_service_config",
                        lambda *a, **k: calls.append("qualify") or SimpleNamespace(client="config"))
    monkeypatch.setattr(_profile_promotion, "recover", lambda _: calls.append("recover"))
    monkeypatch.setattr(_profile_promotion, "publication_state", lambda *a: "applied")
    tmux_backend(monkeypatch, state)
    for _ in range(50):
        with pytest.raises(_startup.ServiceStarting):
            _workload_host.recover_service(request)
    assert calls == ["qualify", "recover"] and state.launches == 1
    assert now[0] < 121
