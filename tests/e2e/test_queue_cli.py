"""E2E smoke coverage for deterministic queue CLI commands."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

import pytest

from loom.cli.main import main
from loom.pipeline.executors.slurm.commands import FakeSlurmCommandRunner
from loom.pipeline.executors.slurm.planning import plan_single_job_slurm_dry_run
from loom.queue import (
    LaunchContract,
    LocalDaemon,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    LocalDaemonSocketServer,
    ResidentWorkerLaunchProfile,
    QueueEnqueueRequest,
    QueueItemStatus,
    QueueService,
    SQLiteQueueRepository,
    load_queue_spec,
)
from loom.queue._remote_stage_execution import ResidentProfileDescriptor
from loom.queue.agent_sessions import (
    AgentPolicyConfig,
    AgentPrincipalPolicy,
    AgentRegistration,
    TransportPrincipalPolicy,
)
from loom.queue.slurm import prepared_slurm_launch
from tests.integration.pipeline.test_slurm_dry_run_planning import _prepared_store


REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_operation_journey(
    example: str, output_root: Path
) -> subprocess.CompletedProcess[str]:
    script = (
        REPO_ROOT
        / "examples"
        / "operations"
        / example
        / f"run_{example.replace('-', '_')}.py"
    )
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=script.parent,
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "LOOM_EXAMPLE_OUTPUT_ROOT": str(output_root),
            "PYTHONPATH": str(REPO_ROOT / "src"),
        },
    )


def _assert_manifest_claims_match_journey(
    example: str, result: subprocess.CompletedProcess[str]
) -> dict[str, Any]:
    assert result.returncode == 0, (
        f"{example} failed with exit {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    result_lines = [
        line.removeprefix("journey_result: ")
        for line in result.stdout.splitlines()
        if line.startswith("journey_result: ")
    ]
    assert len(result_lines) == 1, result.stdout
    journey = json.loads(result_lines[0])
    assert isinstance(journey, dict)

    yaml = pytest.importorskip("yaml")
    manifest_path = REPO_ROOT / "examples" / "operations" / example / "example.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert isinstance(manifest, dict)
    claims = manifest.get("surface_invocations")
    observed = journey.get("surfaces")
    assert isinstance(claims, list)
    assert all(isinstance(item, str) for item in claims)
    assert len(claims) == len(set(claims))
    assert isinstance(observed, list)
    assert set(observed) == set(claims)

    surface_groups = {
        "cli" if item.startswith("cli:") else "python_api" for item in observed
    }
    assert set(manifest["public_surfaces"]) == surface_groups
    assert all(not _pid_exists(int(pid)) for pid in journey["started_pids"])
    return journey


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_managed_remote_operations_manifest_claims_match_journey() -> None:
    with tempfile.TemporaryDirectory(prefix="loom-remote-e2e-") as output:
        result = _run_operation_journey("managed-remote-operations", Path(output))
        journey = _assert_manifest_claims_match_journey(
            "managed-remote-operations", result
        )
        root = Path(journey["root"])
        assert journey["authenticated"] is True
        assert journey["agent_id"] == "machine-B"
        assert journey["final_operation"] == "example-remote-resume"
        assert (root / "tls" / "ca.crt").is_file()
        assert (root / "tls" / "server.crt").is_file()
        assert (root / "tls" / "agent.crt").is_file()
        assert not (root / "deployment" / "coordinator" / "daemon.sock").exists()


def test_managed_ready_stage_slurm_manifest_claims_match_journey() -> None:
    with tempfile.TemporaryDirectory(prefix="loom-slurm-e2e-") as output:
        result = _run_operation_journey("managed-ready-stage-slurm", Path(output))
        journey = _assert_manifest_claims_match_journey(
            "managed-ready-stage-slurm", result
        )
        root = Path(journey["root"])
        assert journey["rejected"] is True
        assert journey["restarted"] is True
        assert journey["result"] == "SUCCEEDED"
        assert journey["released"] is True
        assert (root / "coordinator" / "control.sqlite").is_file()
        assert not (root / "job-private-capability").exists()
        assert not (root / "coordinator" / "daemon.sock").exists()


def test_queue_enqueue_many_example_uses_public_admission_path(tmp_path: Path) -> None:
    output_root = tmp_path / "example-output"
    result = subprocess.run(
        [
            sys.executable,
            str(
                REPO_ROOT
                / "examples"
                / "operations"
                / "durable-many-run-admission"
                / "run_many.py"
            ),
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "LOOM_EXAMPLE_OUTPUT_ROOT": str(output_root)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "enqueued: example-0000",
        "enqueued: example-0001",
    ]
    assert [
        item.queue_item_id
        for item in SQLiteQueueRepository(output_root / "queue.sqlite")
        .list_items(limit=10)
        .items
    ] == ["example-0000", "example-0001"]


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


def test_queue_cli_service_less_slurm_drive_emits_stable_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("yaml")
    store, run_uri = _prepared_store(
        tmp_path / "prepared",
        {"only": ()},
        authority_backed=True,
    )
    planning = plan_single_job_slurm_dry_run(
        run_store=store,
        run_uri=run_uri,
        planning_id="cli-service-less",
        created_at="2026-08-30T00:00:00Z",
    )
    queue_path = tmp_path / "queue.sqlite"
    config_path = tmp_path / "queue.yaml"
    config_path.write_text(
        f"""
        queue:
          service:
            db_path: {queue_path}
          pools:
            - pool_name: slurm-pool
              mode: delegated
              metadata:
                workspace_assumptions_acknowledged: true
          queues:
            - queue_name: slurm
              pool_name: slurm-pool
        """,
        encoding="utf-8",
    )
    service = QueueService.from_spec(load_queue_spec(config_path))
    service.start()
    launch = prepared_slurm_launch(planning)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="cli-prepared",
            queue_name="slurm",
            run_uri=run_uri,
            launch_contract=LaunchContract(
                adapter="slurm",
                entrypoint="prepared-run",
                snapshot=launch.to_snapshot(),
                delegated_verification={"shared_workspace": True},
            ),
        )
    )
    service.stop()
    runner = FakeSlurmCommandRunner(starting_job_id=1700)
    monkeypatch.setattr(
        "loom.pipeline.execution.create_authority_backed_serial_run_store",
        lambda *_args, **_kwargs: store,
    )
    monkeypatch.setattr(
        "loom.queue.slurm.SubprocessSlurmCommandRunner",
        lambda: runner,
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "queue",
                "drive-slurm-foreground",
                str(config_path),
                "--pool",
                "slurm-pool",
                "--run-root",
                str(tmp_path / "prepared" / "runs"),
                "--once",
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    assert stderr.getvalue() == ""
    envelope = json.loads(stdout.getvalue())
    assert set(envelope) == {"schema_version", "ok", "warnings", "result"}
    assert envelope["schema_version"] == "loom.cli.queue.slurm-drive.v1"
    assert envelope["result"]["cycle_count"] == 1
    assert envelope["result"]["dispatched_count"] == 1
    assert envelope["result"]["quiescent"] is False
    assert [call[0] for call in runner.calls].count("sbatch") == 1
    item = SQLiteQueueRepository(queue_path).read_item("cli-prepared")
    assert item is not None and item.status is QueueItemStatus.DISPATCHED


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


def test_managed_local_basic_manifest_claims_match_journey() -> None:
    with tempfile.TemporaryDirectory(prefix="loom-local-e2e-") as output:
        output_root = Path(output)
        roots: set[Path] = set()
        for _ in range(2):
            result = _run_operation_journey("managed-local-basic", output_root)
            journey = _assert_manifest_claims_match_journey(
                "managed-local-basic", result
            )
            assert journey["status"] == "SUCCEEDED"
            assert journey["restarted"] is True
            root = Path(journey["root"])
            roots.add(root)
            assert (root / "coordinator" / "control.sqlite").is_file()
            assert (root / "coordinator" / "execution.sqlite").is_file()
            assert (root / "agent" / "journal.sqlite").is_file()
            assert not (root / "coordinator" / "daemon.sock").exists()
        assert len(roots) == 2
