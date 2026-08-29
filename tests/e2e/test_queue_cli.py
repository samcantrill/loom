"""E2E smoke coverage for deterministic queue CLI commands."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from loom.cli.main import main
from loom.queue import (
    LocalDaemon,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    LocalDaemonSocketServer,
    ResidentWorkerLaunchProfile,
)
from loom.queue._remote_stage_execution import ResidentProfileDescriptor
from loom.queue.agent_sessions import (
    AgentPolicyConfig,
    AgentPrincipalPolicy,
    AgentRegistration,
    TransportPrincipalPolicy,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_queue_cli_preflight_and_start_smoke(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    config_path = tmp_path / "queue.yaml"
    config_path.write_text(
        f"""
        queue:
          service:
            db_path: {tmp_path / "queue.sqlite"}
          pools:
            - pool_name: gpu-pool
              mode: managed
              resources:
                gpu: 1
          queues:
            - queue_name: gpu
              pool_name: gpu-pool
        """,
        encoding="utf-8",
    )
    preflight_out = io.StringIO()
    preflight_err = io.StringIO()
    start_out = io.StringIO()
    start_err = io.StringIO()

    assert (
        main(
            ["queue", "preflight", str(config_path)],
            stdout=preflight_out,
            stderr=preflight_err,
        )
        == 0
    )
    assert (
        main(
            ["queue", "start", str(config_path)],
            stdout=start_out,
            stderr=start_err,
        )
        == 0
    )

    assert preflight_err.getvalue() == ""
    assert "queue preflight" in preflight_out.getvalue()
    assert start_err.getvalue() == ""
    assert "queue service: running" in start_out.getvalue()
    assert "scope: in_process_command" in start_out.getvalue()


def test_queue_cli_pool_status_uses_existing_v1_envelope(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    config_path = tmp_path / "queue.yaml"
    config_path.write_text(
        f"""
        queue:
          service:
            db_path: {tmp_path / "queue.sqlite"}
          pools:
            - pool_name: local-pool
              mode: managed
          queues:
            - queue_name: local
              pool_name: local-pool
        """,
        encoding="utf-8",
    )
    output = io.StringIO()

    assert (
        main(
            [
                "queue",
                "status",
                str(config_path),
                "--pool",
                "local-pool",
                "--format",
                "json",
            ],
            stdout=output,
            stderr=io.StringIO(),
        )
        == 0
    )

    envelope = json.loads(output.getvalue())
    assert envelope["schema_version"] == "loom.cli.queue.status.v1"
    assert set(envelope) == {"schema_version", "ok", "warnings", "result"}
    assert set(envelope["result"]["pool"]) == {
        "pool_name",
        "controller_max_active_items",
        "counts",
        "active_attempts",
    }


def test_session_replacement_cli_uses_the_owner_socket_and_safe_result(
    tmp_path: Path,
) -> None:
    owner = f"uid:{os.getuid()}"
    policy = AgentPolicyConfig(
        agents=(
            AgentPrincipalPolicy(
                "agent-credential",
                "agent-principal",
                "agent-a",
                ("default",),
                ("python",),
            ),
        ),
        principals=(
            TransportPrincipalPolicy(
                "operator-credential",
                owner,
                "operator",
                actions=("replace_session",),
                agent_ids=("agent-a",),
            ),
        ),
    )
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=tmp_path / "runs",
        resident_worker_launch_profile=ResidentWorkerLaunchProfile(
            Path.cwd(),
            Path(sys.executable),
            ResidentProfileDescriptor(
                "test-local",
                "v1",
                "test-project",
                "test-environment",
                "test-executor",
            ).to_dict(),
        ),
        agent_policy=policy,
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    agent = daemon.agent_view(
        LocalDaemonPrincipal(
            "agent-principal", LocalDaemonRole.AGENT, "agent-credential"
        )
    )
    handshake = agent.handshake()
    session = agent.register(
        AgentRegistration(
            idempotency_key="register-lost-agent",
            coordinator_id=str(handshake["coordinator_id"]),
            coordinator_epoch=str(handshake["coordinator_epoch"]),
            agent_root_id="lost-agent-root",
            config_revision="config-1",
            inventory_revision="inventory-1",
            availability_revision="availability-1",
            declared_pools=("default",),
            declared_capabilities=("python",),
            retirement_verifier="01" * 32,
        )
    )
    server = LocalDaemonSocketServer(daemon, config.endpoint)
    server.start()
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        assert (
            main(
                [
                    "queue",
                    "daemon-replace-agent-session",
                    "--endpoint",
                    str(config.endpoint),
                    "--operation-id",
                    "replace-from-cli",
                    "--agent-id",
                    session.agent_id,
                    "--reason",
                    "old agent root is permanently unavailable",
                    "--format",
                    "json",
                ],
                stdout=stdout,
                stderr=stderr,
            )
            == 0
        )
    finally:
        server.stop()
        daemon.stop()

    assert stderr.getvalue() == ""
    envelope = json.loads(stdout.getvalue())
    assert envelope["result"]["state"] == "decision"
    assert envelope["result"]["readiness"] == "withheld"
    assert envelope["result"]["old_session_id"] == session.session_id
    assert envelope["result"]["successor_session_id"] is None
    assert "request_digest" not in envelope["result"]


def test_managed_local_queue_example_is_rerunnable(tmp_path: Path) -> None:
    script = (
        REPO_ROOT
        / "examples"
        / "operations"
        / "managed-local-queue"
        / "run_managed_local_queue.py"
    )
    output_root = tmp_path / "managed-local-queue"
    env = dict(os.environ)
    env["LOOM_EXAMPLE_OUTPUT_ROOT"] = str(output_root)

    for _ in range(2):
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=script.parent,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(
                f"managed-local example failed with exit {result.returncode}\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        assert "coordinator: coordinator-" in result.stdout
        assert "status: SUCCEEDED" in result.stdout
        assert "stages: produce,consume" in result.stdout
        assert "admissions: 1" in result.stdout

    run_roots = sorted(output_root.glob("run-*"))
    assert len(run_roots) == 2
    for run_root in run_roots:
        assert (run_root / "coordinator" / "control.sqlite").is_file()
        assert (run_root / "coordinator" / "execution.sqlite").is_file()
        assert (run_root / "agent" / "journal.sqlite").is_file()
        assert not (run_root / "coordinator" / "daemon.sock").exists()
