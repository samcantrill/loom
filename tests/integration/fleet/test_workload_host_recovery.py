"""Real managed supervisor startup must acquire the live agent's journal lock."""

from __future__ import annotations

from dataclasses import replace
import os
import sqlite3
import subprocess
import sys
import time
from types import SimpleNamespace
from threading import Thread
from typing import Any

import pytest

from loom.fleet import _host, _services, _workload_host
from loom.queue.agent_session_transport import LocalDaemonAgentHttpClient
from loom.queue._agent_process_supervisor import (
    AgentProcessSupervisorClient,
    AgentProcessSupervisorError,
    _service_configuration,
)
from loom.queue._service_lifetime import record_process
from tests.integration.queue.test_agent_profile_promotion import client, request, apply

pytestmark = pytest.mark.integration


def test_recovery_stops_owned_agent_then_uses_actual_managed_supervisor_start(
    tmp_path, monkeypatch
):
    original, old, replacement = client(tmp_path)
    replacement = replace(replacement, external_supervisor=True)
    original._config = replace(old, external_supervisor=True)
    original._trusted_config_loader = lambda: replacement
    root = replacement.agent_root
    assert root is not None
    root_id = original.agent_root_id
    control = request(old, replacement, root_id)
    assert apply(original, control).code == "applied"
    original._require_journal().acknowledge_control(control.operation_id)
    record_process(
        root, stopped=False, coordinator_id="coordinator", session_id="session"
    )
    secret = (root / "supervisor/service.secret").read_bytes()
    with sqlite3.connect(root / "control.sqlite") as conn:
        before = conn.execute(
            "SELECT request_json,effect_json,acknowledged FROM agent_controls_local"
        ).fetchall()
    admin = tmp_path / "admin"
    admin.mkdir(mode=0o700)
    selection = {
        "root": str(root),
        "config": str(tmp_path / "agent.json"),
        "admin": str(admin),
        "name": "worker",
        "service_manager": "systemd-user",
        "coordinator_id": "coordinator",
        "expected_root_id": root_id,
        "release": {"descriptor_sha256": "same-release"},
        "promotion_id": control.operation_id,
        "allow_communication_stop": True,
    }
    _host.atomic(admin / "service.json", selection)
    monkeypatch.setattr(
        _workload_host,
        "load_outbound_agent_service_config",
        lambda *a, **k: SimpleNamespace(client=replacement),
    )
    monkeypatch.setattr(_workload_host, "payload", lambda _: {"current": "promoted"})
    monkeypatch.setattr(_host, "payload", lambda _: {})
    monkeypatch.setattr(_services, "prerequisites", lambda: None)
    script = """from pathlib import Path
import sys
from loom.queue._agent_process_supervisor import AgentProcessSupervisorService, _service_configuration
root = Path(sys.argv[1])
AgentProcessSupervisorService.serve_initialized(root,
    configuration=_service_configuration(root / 'supervisor'),
    immutable_fingerprint=sys.argv[2], active_fingerprint=sys.argv[3])
"""
    command = [
        sys.executable,
        "-c",
        script,
        str(root),
        str(replacement.deployment_configuration_fingerprint),
        str(replacement.active_configuration_fingerprint),
    ]
    # This is the actual failing installed path, not start_empty_initialized.
    refused = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert (
        refused.returncode != 0
        and "remote agent root is already locked" in refused.stderr
    )
    running: dict[str, Any] = {"agent": original, "supervisor": None}
    mutations = []
    supervisor_client = None
    later_history = []

    def systemctl(*args):
        nonlocal supervisor_client, later_history
        supervisor_unit = _services.unit_name(selection, "supervisor")
        agent_unit = _services.unit_name(selection, "agent")
        if args[0] == "show":
            if args[1] == supervisor_unit:
                process = running["supervisor"]
                return (
                    str(process.pid)
                    if process is not None and process.poll() is None
                    else "0"
                )
            assert args[1] == agent_unit
            return str(os.getpid()) if running["agent"] is not None else "0"
        if args[0] in {"daemon-reload", "enable"}:
            return ""
        mutations.append(args)
        if args == ("stop", agent_unit):
            assert running["agent"] is not None
            # A supported later drain can arrive after the operator observation.
            # Restart must preserve it rather than recreating promotion policy.
            from loom.queue.agent_sessions import AgentControl, AgentControlKind

            current = running["agent"]
            later = AgentControl(
                "later-drain",
                AgentControlKind.DRAIN,
                "agent-a",
                "session",
                current._require_journal().session("session").config_revision,
                None,
                False,
                "independent later policy",
            )
            assert apply(current, later).code == "applied"
            current._require_journal().acknowledge_control(later.operation_id)
            with sqlite3.connect(root / "control.sqlite") as conn:
                later_history = conn.execute(
                    "SELECT request_json,effect_json,acknowledged FROM agent_controls_local"
                ).fetchall()
            assert all(row in later_history for row in before)
            running["agent"].close()
            running["agent"] = None
            record_process(root, stopped=True)
        elif args == ("start", supervisor_unit, agent_unit):
            assert running["agent"] is None
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            running["supervisor"] = process
            Thread(target=process.wait, daemon=True).start()
            deadline = time.monotonic() + 15
            while supervisor_client is None:
                assert process.poll() is None, process.communicate()
                try:
                    supervisor_client = AgentProcessSupervisorClient(
                        root, _service_configuration(root / "supervisor")
                    )
                except AgentProcessSupervisorError:
                    assert time.monotonic() < deadline
                    time.sleep(0.02)
            running["agent"] = LocalDaemonAgentHttpClient(replacement)
            record_process(
                root, stopped=False, coordinator_id="coordinator", session_id="session"
            )
        else:
            pytest.fail("unexpected service mutation: " + repr(args))
        return ""

    monkeypatch.setattr(_services, "systemctl", systemctl)
    try:
        assert (
            _workload_host.recover_service(selection)["publication_state"] == "applied"
        )
        assert len(mutations) == 2
        restored = running["agent"]
        assert (
            restored is not None
            and restored.agent_root_id == root_id
            and restored._drained
        )
        assert restored._require_journal().session("session").session_id == "session"
        assert (root / "supervisor/service.secret").read_bytes() == secret
        with sqlite3.connect(root / "control.sqlite") as conn:
            assert (
                conn.execute(
                    "SELECT request_json,effect_json,acknowledged FROM agent_controls_local"
                ).fetchall()
                == later_history
            )
        # Repeated continuation with healthy services cannot stop them again.
        assert (
            _workload_host.recover_service(
                {**selection, "allow_communication_stop": False}
            )["publication_state"]
            == "applied"
        )
        assert len(mutations) == 2
        with sqlite3.connect(root / "control.sqlite") as conn:
            assert (
                conn.execute(
                    "SELECT request_json,effect_json,acknowledged FROM agent_controls_local"
                ).fetchall()
                == later_history
            )
    finally:
        if running["agent"] is not None:
            running["agent"].close()
        try:
            if supervisor_client is not None:
                supervisor_client.shutdown_for_test()
        finally:
            process = running["supervisor"]
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                process.communicate(timeout=15)
