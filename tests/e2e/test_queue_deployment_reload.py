"""Fresh-process proof for protected coordinator reload and restart."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
from time import monotonic, sleep

import pytest

from loom.queue import DaemonStatus, LocalDaemonSocketClient
from loom.queue._remote_stage_execution import (
    REGULAR_FILE_RELAY_CAPABILITY,
    REMOTE_EXECUTION_CAPABILITY,
)
from tests.support.mutual_tls import (
    certificate_fingerprint,
    mutual_tls_credentials,
)


pytestmark = pytest.mark.e2e


def test_daemon_service_reloads_exact_source_and_restarts_active_revision(
    tmp_path: Path,
) -> None:
    source = tmp_path / "coordinator.json"
    payload = _coordinator_payload(tmp_path, cpu_capacity=1)
    _write_protected(source, payload)
    initialized = _run_cli("queue", "daemon-init", str(source), "--format", "json")
    assert initialized.returncode == 0, initialized.stderr

    endpoint = tmp_path / "deployment" / "coordinator" / "daemon.sock"
    first = _start_service(source)
    try:
        before = _wait_for_status(first, endpoint)
        payload["embedded_profile"]["cpu_capacity"] = 2  # type: ignore[index]
        _write_protected(source, payload)
        reloaded = _run_cli(
            "queue",
            "daemon-scheduling-reload",
            "--endpoint",
            str(endpoint),
            "--operation-id",
            "e2e-source-reload-1",
            "--expected-scheduling-epoch",
            before.scheduling_epoch,
            "--format",
            "json",
        )
        assert reloaded.returncode == 0, reloaded.stderr
        result = json.loads(reloaded.stdout)["result"]
        assert result["state"] == "applied"
        assert result["configuration_revision"] == 2
        assert result["scheduling_epoch"] != before.scheduling_epoch
        after = LocalDaemonSocketClient(endpoint).status()
        assert after.scheduling_epoch == result["scheduling_epoch"]
    finally:
        _stop_service(first)

    restarted = _start_service(source)
    try:
        restored = _wait_for_status(restarted, endpoint)
        assert restored.coordinator_id == before.coordinator_id
        assert restored.coordinator_epoch != before.coordinator_epoch
        assert restored.scheduling_epoch == result["scheduling_epoch"]
    finally:
        _stop_service(restarted)


def test_outbound_agent_service_reloads_exact_source_and_restarts_active_revision(
    tmp_path: Path,
) -> None:
    credentials = mutual_tls_credentials(tmp_path / "tls")
    port = _available_port()
    coordinator_source = tmp_path / "coordinator.json"
    agent_source = tmp_path / "agent.json"
    coordinator_payload = _networked_coordinator_payload(
        tmp_path, credentials=credentials, port=port
    )
    agent_payload = _outbound_agent_payload(
        tmp_path, credentials=credentials, port=port, cpu_capacity=1
    )
    _write_protected(coordinator_source, coordinator_payload)
    _write_protected(agent_source, agent_payload)
    for command, source in (
        ("daemon-init", coordinator_source),
        ("agent-init", agent_source),
    ):
        initialized = _run_cli("queue", command, str(source), "--format", "json")
        assert initialized.returncode == 0, initialized.stderr

    endpoint = tmp_path / "deployment" / "coordinator" / "daemon.sock"
    control_database = tmp_path / "deployment" / "coordinator" / "control.sqlite"
    coordinator = _start_service(coordinator_source)
    agent: subprocess.Popen[str] | None = None
    restarted_agent: subprocess.Popen[str] | None = None
    try:
        _wait_for_status(coordinator, endpoint)
        agent = _start_agent_service(agent_source)
        session_id, config_revision = _wait_for_agent_offer(
            agent, control_database, cpu_capacity=1
        )

        profile = agent_payload["resident_profiles"]
        assert isinstance(profile, list) and isinstance(profile[0], dict)
        profile[0]["cpu_capacity"] = 2
        registration = agent_payload["registration"]
        assert isinstance(registration, dict)
        registration["availability_revision"] = "availability-2"
        _write_protected(agent_source, agent_payload)
        reloaded = _run_cli(
            "queue",
            "daemon-agent-reload",
            "--endpoint",
            str(endpoint),
            "--operation-id",
            "e2e-agent-source-reload-1",
            "--agent-id",
            "agent-a",
            "--session-id",
            session_id,
            "--config-revision",
            config_revision,
            "--format",
            "json",
        )
        assert reloaded.returncode == 0, reloaded.stderr
        result = json.loads(reloaded.stdout)["result"]
        assert result["state"] == "applied"
        assert result["code"] == "applied"
        reloaded_revision = _wait_for_session_revision(
            control_database,
            session_id=session_id,
            previous_revision=config_revision,
        )
        resumed = _run_cli(
            "queue",
            "daemon-agent-resume",
            "--endpoint",
            str(endpoint),
            "--operation-id",
            "e2e-agent-source-resume-1",
            "--agent-id",
            "agent-a",
            "--session-id",
            session_id,
            "--config-revision",
            reloaded_revision,
            "--format",
            "json",
        )
        assert resumed.returncode == 0, resumed.stderr
        resumed_session, resumed_revision = _wait_for_agent_offer(
            agent, control_database, cpu_capacity=2
        )
        assert resumed_session == session_id
        assert resumed_revision == reloaded_revision

        _stop_service(agent)
        agent = None
        restarted_agent = _start_agent_service(agent_source)
        restarted_session, restarted_revision = _wait_for_agent_offer(
            restarted_agent, control_database, cpu_capacity=2
        )
        assert restarted_session == session_id
        assert restarted_revision == reloaded_revision
    finally:
        if agent is not None:
            _stop_service(agent)
        if restarted_agent is not None:
            _stop_service(restarted_agent)
        _stop_service(coordinator)


def _coordinator_payload(tmp_path: Path, *, cpu_capacity: int) -> dict[str, object]:
    return {
        "schema_version": 2,
        "kind": "loom.coordinator-service",
        "deployment_root": "deployment",
        "run_store_root": "runs",
        "machine_id": "e2e-machine",
        "poll_interval_seconds": 0.01,
        "max_accepted_time_step_seconds": 60,
        "embedded_profile": {
            "descriptor": {
                "profile_id": "e2e-local",
                "revision": "v1",
                "project_fingerprint": "project-1",
                "environment_fingerprint": "environment-1",
                "executor_fingerprint": "executor-1",
            },
            "project_root": str(tmp_path),
            "python_executable": sys.executable,
            "cpu_capacity": cpu_capacity,
            "memory_capacity_bytes": 0,
            "gpu_devices": [],
            "environment": {},
        },
        "remote_profiles": [],
        "agent_policy": {
            "revision": "policy-1",
            "agents": [],
            "principals": [
                {
                    "credential_id": "local-owner",
                    "principal_id": f"uid:{os.getuid()}",
                    "role": "operator",
                    "actions": ["scheduling_reload"],
                    "agent_ids": [],
                    "pools": [],
                }
            ],
        },
        "agent_server": None,
        "authority": {"kind": "embedded"},
    }


def _networked_coordinator_payload(
    tmp_path: Path, *, credentials: dict[str, Path], port: int
) -> dict[str, object]:
    payload = _coordinator_payload(tmp_path, cpu_capacity=1)
    remote_profile = _resident_profile_payload(
        tmp_path, profile_id="remote-1", cpu_capacity=1
    )
    payload["remote_profiles"] = [remote_profile["descriptor"]]
    payload["agent_policy"] = {
        "revision": "policy-1",
        "agents": [
            {
                "credential_id": "agent-credential",
                "principal_id": "agent-principal",
                "agent_id": "agent-a",
                "pools": ["default"],
                "capabilities": [
                    "python",
                    REMOTE_EXECUTION_CAPABILITY,
                    REGULAR_FILE_RELAY_CAPABILITY,
                ],
                "gpu_devices": [],
            }
        ],
        "principals": [
            {
                "credential_id": "local-owner",
                "principal_id": f"uid:{os.getuid()}",
                "role": "operator",
                "actions": ["reload", "resume"],
                "agent_ids": ["agent-a"],
                "pools": [],
            }
        ],
    }
    payload["agent_server"] = {
        "host": "localhost",
        "port": port,
        "certificate_path": str(credentials["server"].with_suffix(".crt")),
        "private_key_path": str(credentials["server"].with_suffix(".key")),
        "client_ca_path": str(credentials["ca"].with_suffix(".crt")),
        "credential_fingerprints": {
            certificate_fingerprint(
                credentials["agent"].with_suffix(".crt")
            ): "agent-credential"
        },
    }
    return payload


def _outbound_agent_payload(
    tmp_path: Path,
    *,
    credentials: dict[str, Path],
    port: int,
    cpu_capacity: int,
) -> dict[str, object]:
    return {
        "schema_version": 2,
        "kind": "loom.outbound-agent-service",
        "agent_root": "remote-agent",
        "url": f"https://localhost:{port}",
        "server_ca_path": str(credentials["ca"].with_suffix(".crt")),
        "certificate_path": str(credentials["agent"].with_suffix(".crt")),
        "private_key_path": str(credentials["agent"].with_suffix(".key")),
        "resident_profiles": [
            _resident_profile_payload(
                tmp_path, profile_id="remote-1", cpu_capacity=cpu_capacity
            )
        ],
        "registration": {
            "config_revision": "config-1",
            "inventory_revision": "inventory-1",
            "availability_revision": "availability-1",
            "pools": ["default"],
            "capabilities": [
                "python",
                REMOTE_EXECUTION_CAPABILITY,
                REGULAR_FILE_RELAY_CAPABILITY,
            ],
        },
        "reconnect_seconds": 0.05,
    }


def _resident_profile_payload(
    tmp_path: Path, *, profile_id: str, cpu_capacity: int
) -> dict[str, object]:
    return {
        "descriptor": {
            "profile_id": profile_id,
            "revision": "v1",
            "project_fingerprint": "project-1",
            "environment_fingerprint": "environment-1",
            "executor_fingerprint": "executor-1",
        },
        "project_root": str(tmp_path),
        "python_executable": sys.executable,
        "cpu_capacity": cpu_capacity,
        "memory_capacity_bytes": 0,
        "gpu_devices": [],
        "environment": {},
    }


def _write_protected(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)


def _cli_command(*args: str) -> list[str]:
    return [
        sys.executable,
        "-c",
        "from loom.cli.main import main; raise SystemExit(main())",
        *args,
    ]


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _cli_command(*args),
        cwd=Path(__file__).parents[2],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def _start_service(source: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        _cli_command("queue", "daemon-serve", str(source), "--format", "json"),
        cwd=Path(__file__).parents[2],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _start_agent_service(source: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        _cli_command("queue", "agent-serve", str(source), "--format", "json"),
        cwd=Path(__file__).parents[2],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_for_status(
    process: subprocess.Popen[str], endpoint: Path
) -> DaemonStatus:
    deadline = monotonic() + 15
    last_error: Exception | None = None
    while monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            pytest.fail(
                "daemon service exited before readiness\n"
                f"stdout:\n{stdout}\nstderr:\n{stderr}"
            )
        try:
            return LocalDaemonSocketClient(endpoint).status()
        except Exception as exc:  # startup spans process, socket, and schema owners
            last_error = exc
            sleep(0.05)
    pytest.fail(f"daemon service did not become ready: {last_error}")


def _stop_service(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
    try:
        process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=10)


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_agent_offer(
    process: subprocess.Popen[str],
    control_database: Path,
    *,
    cpu_capacity: int,
) -> tuple[str, str]:
    deadline = monotonic() + 20
    last_offer: object = None
    while monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            pytest.fail(
                "outbound agent exited before publishing capacity\n"
                f"stdout:\n{stdout}\nstderr:\n{stderr}"
            )
        if control_database.is_file():
            with sqlite3.connect(control_database) as connection:
                connection.row_factory = sqlite3.Row
                row = connection.execute(
                    "SELECT s.session_id, s.config_revision, o.offer_json "
                    "FROM agent_sessions s JOIN agent_offers o "
                    "ON o.session_id = s.session_id "
                    "WHERE s.agent_id = 'agent-a' AND s.state = 'ACTIVE' "
                    "AND o.current = 1 ORDER BY o.accepted_at DESC LIMIT 1"
                ).fetchone()
            if row is not None:
                last_offer = json.loads(str(row["offer_json"]))
                if (
                    isinstance(last_offer, dict)
                    and _offered_cpu_capacity(last_offer) == cpu_capacity
                ):
                    return str(row["session_id"]), str(row["config_revision"])
        sleep(0.05)
    pytest.fail(
        f"outbound agent did not publish CPU capacity {cpu_capacity}: {last_offer}"
    )


def _offered_cpu_capacity(offer: dict[str, object]) -> int:
    atoms = offer.get("capacity_atoms")
    if not isinstance(atoms, list):
        return -1
    total = 0
    for value in atoms:
        if not isinstance(value, dict) or value.get("owner_resource_kind") != "cpu":
            continue
        amount = value.get("amount")
        if (
            not isinstance(amount, dict)
            or amount.get("denominator") != 1
            or not isinstance(amount.get("numerator"), int)
        ):
            return -1
        total += int(amount["numerator"])
    return total


def _wait_for_session_revision(
    control_database: Path,
    *,
    session_id: str,
    previous_revision: str,
) -> str:
    deadline = monotonic() + 5
    while monotonic() < deadline:
        with sqlite3.connect(control_database) as connection:
            row = connection.execute(
                "SELECT config_revision FROM agent_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is not None and str(row[0]) != previous_revision:
            return str(row[0])
        sleep(0.02)
    pytest.fail("agent session did not install its reloaded config revision")
