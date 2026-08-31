"""End-to-end coverage for the service-less run-inspection CLI journey."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import cast

import pytest

from loom.pipeline.executors.slurm.commands import FakeSlurmCommandRunner
from loom.pipeline.executors.slurm.planning import plan_single_job_slurm_dry_run
from loom.queue import (
    LaunchContract,
    LocalDaemon,
    LocalDaemonConfig,
    QueueController,
    QueueEnqueueRequest,
)
from loom.queue.agent_session_transport import AgentTlsServerConfig
from loom.queue.agent_session_transport import LocalDaemonAgentHttpServer
from loom.queue.agent_sessions import AgentPolicyConfig, TransportPrincipalPolicy
from loom.queue.slurm import SlurmQueueDispatchAdapter, prepared_slurm_launch
from loom.serialization import PlainData
from tests.integration.pipeline.test_slurm_dry_run_planning import _prepared_store
from tests.integration.queue.test_agent_session_transport import (
    _credentials,
    _fingerprint,
    _local_launch_profile,
)
from tests.integration.queue.test_delegated_slurm_controller import (
    _clock,
    _started_service,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_remote_cli_inspects_admitted_run_over_mtls_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    credentials = _credentials(tmp_path / "tls")
    run_uri = "file:///runs/remote-cli"
    result = _remote_result(run_uri)
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "agent-root",
        tmp_path / "runs",
        _local_launch_profile(),
        agent_policy=AgentPolicyConfig(
            principals=(
                TransportPrincipalPolicy(
                    "query-credential", "query-principal", "query"
                ),
            )
        ),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    monkeypatch.setattr(daemon, "admission_for_run_uri", lambda _uri: object())
    server = LocalDaemonAgentHttpServer(
        daemon,
        AgentTlsServerConfig(
            "localhost",
            0,
            credentials["server"].with_suffix(".crt"),
            credentials["server"].with_suffix(".key"),
            credentials["ca"].with_suffix(".crt"),
            {
                _fingerprint(credentials["query"].with_suffix(".crt")): (
                    "query-credential"
                )
            },
        ),
        inspect_run=lambda _run_uri: result,
    )
    server.start()
    client_config = tmp_path / "inspection-client.json"
    client_config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "loom.run-inspection-client",
                "url": f"https://localhost:{server.port}",
                "server_ca_path": str(credentials["ca"].with_suffix(".crt")),
                "certificate_path": str(credentials["query"].with_suffix(".crt")),
                "private_key_path": str(credentials["query"].with_suffix(".key")),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    client_config.chmod(0o600)
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "from loom.cli.main import main; raise SystemExit(main())",
                "inspect-run",
                run_uri,
                "--remote-config",
                str(client_config),
                "--format",
                "json",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        server.stop()
        daemon.stop()

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    envelope = json.loads(completed.stdout)
    assert envelope == {
        "schema_version": "loom.cli.inspect_run.v1",
        "ok": True,
        "result": result,
        "warnings": [],
    }


def test_direct_cli_inspects_service_less_run_after_driver_exit(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_store(
        tmp_path,
        {"build": ()},
        authority_backed=True,
    )
    planning = plan_single_job_slurm_dry_run(
        run_store=store,
        run_uri=run_uri,
        planning_id="inspect-cli",
        created_at="2026-08-30T00:00:00Z",
    )
    service = _started_service(tmp_path, clock=_clock("2026-08-30T00:00:00Z"))
    launch = prepared_slurm_launch(planning)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="inspect-cli-item",
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
    controller = QueueController(
        service,
        adapters={
            "slurm": SlurmQueueDispatchAdapter(
                command_runner=FakeSlurmCommandRunner(starting_job_id=1200),
                run_store=store,
            )
        },
    )
    driven = controller.drive_foreground(
        pool_name="slurm-pool",
        until_quiescent=True,
    )
    assert driven.quiescent is True

    queue_config = tmp_path / "queue.json"
    queue_config.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "db_path": str(tmp_path / "queue.sqlite"),
                "pools": [
                    {
                        "pool_name": "slurm-pool",
                        "mode": "delegated",
                        "resources": {"gpu": 8},
                    }
                ],
                "queues": [{"queue_name": "slurm", "pool_name": "slurm-pool"}],
                "controller": {"max_active_items": 1},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    del controller, service
    before_names = _queue_file_names(tmp_path)
    before = _durable_queue_files(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from loom.cli.main import main; raise SystemExit(main())",
            "inspect-run",
            run_uri,
            "--direct",
            "--queue-config",
            str(queue_config),
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    envelope = json.loads(completed.stdout)
    assert envelope["schema_version"] == "loom.cli.inspect_run.v1"
    assert envelope["ok"] is True
    result = envelope["result"]
    assert result["run_uri"] == run_uri
    assert result["queue_item_id"] == "inspect-cli-item"
    assert result["admission_id"] is None
    assert {axis["name"] for axis in result["axes"]} == {
        "admission",
        "lifecycle",
        "scheduling",
        "assignment",
        "external_scheduler",
        "transfer_result",
        "cancellation",
        "materialization",
        "service_health",
    }
    assert "SECRET_SHOULD_NOT_BE_COPIED" not in completed.stdout
    assert before_names == _queue_file_names(tmp_path)
    assert before == _durable_queue_files(tmp_path)


def _queue_file_names(root: Path) -> set[str]:
    return {path.name for path in root.glob("queue.sqlite*") if path.is_file()}


def _durable_queue_files(root: Path) -> dict[str, bytes]:
    """Exclude SQLite's transient shared-memory lock table from byte checks."""

    return {
        path.name: path.read_bytes()
        for path in sorted(root.glob("queue.sqlite*"))
        if path.is_file() and not path.name.endswith("-shm")
    }


def _remote_result(run_uri: str) -> dict[str, PlainData]:
    names = (
        "admission",
        "lifecycle",
        "scheduling",
        "assignment",
        "external_scheduler",
        "transfer_result",
        "cancellation",
        "materialization",
        "service_health",
    )
    return cast(
        dict[str, PlainData],
        {
            "schema_version": 1,
            "run_uri": run_uri,
            "as_of": "2026-08-30T00:00:00Z",
            "summary": "RUNNING",
            "queue_item_id": "remote-item",
            "admission_id": "remote-admission",
            "axes": [
                {
                    "name": name,
                    "owner": "test",
                    "availability": "available",
                    "state": "RUNNING",
                    "revision": 1,
                    "observed_at": "2026-08-30T00:00:00Z",
                    "freshness": "current",
                    "code": None,
                }
                for name in names
            ],
            "stages": [],
            "locations": [],
            "truncation": [
                {"collection": "stages", "total_count": 0, "returned_count": 0},
                {"collection": "locations", "total_count": 0, "returned_count": 0},
            ],
        },
    )
