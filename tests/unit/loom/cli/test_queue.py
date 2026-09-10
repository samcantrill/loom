"""Unit coverage for the queue CLI wrapper."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
import io
import json
from pathlib import Path
import sys

import pytest

from loom.cli.main import main
from loom.queue import (
    LocalDaemon,
    LocalDaemonConfig,
    LocalDaemonSocketServer,
    ResidentWorkerLaunchProfile,
    QueueEnqueueRequest,
    QueueService,
    load_queue_spec,
)
from loom.queue._remote_stage_execution import ResidentProfileDescriptor
from loom.queue.resources import EffectiveAgentCapacity
import loom.queue.resources as queue_resources


pytestmark = pytest.mark.unit


def test_queue_status_json_reports_item_and_ownership(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    config_path = _queue_config(tmp_path)
    _enqueue(config_path, "item-1")
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        [
            "queue",
            "status",
            str(config_path),
            "--item",
            "item-1",
            "--format",
            "json",
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == "loom.cli.queue.status.v1"
    assert payload["ok"] is True
    assert payload["result"]["item"]["item"]["queue_item_id"] == "item-1"
    assert "authority remains" in payload["result"]["ownership"]["authority_state"]


def test_queue_preflight_skips_authority_when_no_authority_flags_are_supplied(
    tmp_path: Path,
) -> None:
    pytest.importorskip("yaml")
    config_path = _queue_config(tmp_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        ["queue", "preflight", str(config_path)],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert "SKIP queue.authority.connection" in stdout.getvalue()


@pytest.mark.parametrize("command", ["agent-check", "daemon-check"])
def test_role_check_reports_unavailable_effective_capacity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    config_path = (
        _outbound_agent_service_config(tmp_path)
        if command == "agent-check"
        else _coordinator_service_config(tmp_path)
    )
    agent_path = (
        config_path if command == "agent-check" else tmp_path / "local-agent.yaml"
    )
    payload = json.loads(agent_path.read_text(encoding="utf-8"))
    payload["resources"] = {
        "cpu_capacity": 1,
        "memory_capacity_bytes": 0,
        "gpu": {"provider": "nvidia", "devices": "none"},
    }
    agent_path.write_text(json.dumps(payload), encoding="utf-8")
    agent_path.chmod(0o600)
    monkeypatch.setattr(
        queue_resources,
        "observe_effective_agent_capacity",
        lambda: EffectiveAgentCapacity(cpu_capacity=None, memory_capacity_bytes=None),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        ["queue", command, str(config_path), "--format", "json"],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert json.loads(stdout.getvalue())["result"]["effective_capacity"] == {
        "cpu_capacity": None,
        "memory_capacity_bytes": None,
    }
    assert not (tmp_path / "deployment").exists()


def test_queue_cancel_records_queue_local_cancellation(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    config_path = _queue_config(tmp_path)
    _enqueue(config_path, "item-1")
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        [
            "queue",
            "cancel",
            str(config_path),
            "item-1",
            "--reason",
            "operator-requested",
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert "queue cancel item-1: CANCELLED" in stdout.getvalue()
    assert "operator-requested" in stdout.getvalue()


def test_queue_drain_foreground_dispatches_fake_item(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    config_path = _queue_config(tmp_path)
    _enqueue(config_path, "item-1")
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        [
            "queue",
            "drain-foreground",
            str(config_path),
            "--max-items",
            "1",
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert "queue drain foreground: 1 step(s)" in stdout.getvalue()
    assert "dispatched: item-1 SUCCEEDED" in stdout.getvalue()


def test_queue_daemon_init_creates_fresh_role_roots(tmp_path: Path) -> None:
    config = _coordinator_service_config(tmp_path)
    deployment = tmp_path / "deployment"
    stdout = io.StringIO()

    exit_code = main(
        [
            "queue",
            "daemon-init",
            str(config),
            "--format",
            "json",
        ],
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert exit_code == 0
    assert json.loads(stdout.getvalue())["result"]["operation"] == "initialize"
    assert (deployment / "coordinator" / "control.sqlite").is_file()
    assert (deployment / "agent" / "control.sqlite").is_file()
    assert (deployment / "deployment-binding.json").is_file()


@pytest.mark.optional_dependency
def test_queue_role_check_uses_only_its_explicit_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _coordinator_service_config(tmp_path)
    payload = json.loads(config.read_text(encoding="utf-8"))
    agent_path = tmp_path / "local-agent.yaml"
    agent_payload = json.loads(agent_path.read_text(encoding="utf-8"))
    profile = agent_payload["resident_profiles"][0]
    assert isinstance(profile, dict)
    profile["cpu_capacity"] = "${oc.env:LOOM_ROLE_CPU}"
    local_agent = payload["local_agent"]
    assert isinstance(local_agent, dict)
    local_agent["env_file"] = "coordinator.env"
    config.write_text(json.dumps(payload), encoding="utf-8")
    config.chmod(0o600)
    agent_path.write_text(json.dumps(agent_payload), encoding="utf-8")
    agent_path.chmod(0o600)
    environment = tmp_path / "coordinator.env"
    environment.write_text("LOOM_ROLE_CPU=1\n", encoding="utf-8")
    environment.chmod(0o600)
    monkeypatch.setenv("LOOM_ROLE_CPU", "9")
    stdout = io.StringIO()

    result = main(
        [
            "queue",
            "daemon-check",
            str(config),
            "--env-file",
            str(environment),
            "--format",
            "json",
        ],
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert result == 0
    assert json.loads(stdout.getvalue())["result"]["operation"] == "check"
    assert not (tmp_path / "deployment").exists()


def test_queue_daemon_profile_flags_are_a_complete_hard_cut(tmp_path: Path) -> None:
    result = main(
        [
            "queue",
            "daemon-init",
            "--coordinator-root",
            str(tmp_path / "coordinator"),
            "--agent-root",
            str(tmp_path / "agent"),
            "--run-store-root",
            str(tmp_path / "runs"),
        ],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert result == 2


def test_queue_agent_init_uses_one_protected_config(tmp_path: Path) -> None:
    config = _outbound_agent_service_config(tmp_path)
    stdout = io.StringIO()

    result = main(
        ["queue", "agent-init", str(config), "--format", "json"],
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert result == 0
    assert json.loads(stdout.getvalue())["result"]["operation"] == "agent-initialize"
    assert (tmp_path / "remote-agent/control.sqlite").is_file()
    assert (tmp_path / "remote-agent/role-binding.json").is_file()
    from loom.queue.agent_session_transport import LocalDaemonAgentHttpClient
    from loom.queue.deployment import load_outbound_agent_service_config

    client = LocalDaemonAgentHttpClient(
        load_outbound_agent_service_config(config).client
    )
    try:
        assert client._supervisor is not None  # noqa: SLF001
        client._supervisor.shutdown_for_test()  # noqa: SLF001
    finally:
        client.close()


def test_queue_daemon_status_uses_owner_only_socket_client(tmp_path: Path) -> None:
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=tmp_path / "runs",
        resident_worker_launch_profile=_launch_profile(),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    server = LocalDaemonSocketServer(daemon, config.endpoint)
    server.start()
    stdout = io.StringIO()
    try:
        exit_code = main(
            [
                "queue",
                "daemon-status",
                "--endpoint",
                str(config.endpoint),
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=io.StringIO(),
        )
    finally:
        server.stop()
        daemon.stop()

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["schema_version"] == "loom.cli.queue.local-daemon.v5"
    assert payload["result"]["service_health"] == "healthy"


def test_daemon_client_connection_options_are_mutually_exclusive(tmp_path: Path) -> None:
    stderr = io.StringIO()

    exit_code = main(
        [
            "queue",
            "daemon-status",
            "--endpoint",
            str(tmp_path / "daemon.sock"),
            "--connection",
            str(tmp_path / "client.yaml"),
        ],
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert exit_code == 2
    assert "not allowed with argument" in stderr.getvalue()


def test_queue_daemon_admission_renders_private_diagnostic_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from loom.queue import LocalDaemonSocketClient

    payload = {
        "admission": {"admission_id": "admission"},
        "authority": {},
        "owners": {
            "run_result": {
                "availability": "unavailable",
                "diagnostic_failure": {
                    "schema": "loom.diagnostic.v1",
                    "type": "builtins.RuntimeError",
                    "message": "cannot read /private/run",
                    "links": [
                        {
                            "relation": "cause",
                            "record": {
                                "type": "builtins.OSError",
                                "message": "permission denied",
                                "links": [],
                            },
                        }
                    ],
                },
            }
        },
    }

    class Result:
        def to_dict(self) -> dict[str, object]:
            return payload

    monkeypatch.setattr(
        LocalDaemonSocketClient, "admission", lambda _self, _admission_id: Result()
    )
    text_stdout = io.StringIO()

    assert (
        main(
            [
                "queue",
                "daemon-admission",
                "--endpoint",
                str(tmp_path / "daemon.sock"),
                "admission",
            ],
            stdout=text_stdout,
            stderr=io.StringIO(),
        )
        == 0
    )
    assert "run-result diagnostic failure:" in text_stdout.getvalue()
    assert "builtins.RuntimeError: cannot read /private/run" in text_stdout.getvalue()
    assert "cause:" in text_stdout.getvalue()

    json_stdout = io.StringIO()
    assert (
        main(
            [
                "queue",
                "daemon-admission",
                "--endpoint",
                str(tmp_path / "daemon.sock"),
                "admission",
                "--format",
                "json",
            ],
            stdout=json_stdout,
            stderr=io.StringIO(),
        )
        == 0
    )
    assert json.loads(json_stdout.getvalue())["result"] == payload


def test_admission_text_and_json_preserve_portable_worker_failure_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loom.diagnostics.diagnostic_failure import _capture_exception_details
    from loom.pipeline.execution.models import ExecutionFailure
    from loom.queue import LocalDaemonSocketClient

    cause = FileNotFoundError("missing /worker/data/product.json")
    cause.add_note("Prepare the product on the worker first.")
    try:
        raise RuntimeError("training input preparation failed") from cause
    except RuntimeError as error:
        details = _capture_exception_details(error)
    inner = ExecutionFailure(
        schema_version=1,
        run_uri="loom-agent:assignment-1",
        stage_name="fit",
        attempt=1,
        failed_at="2020-01-01T00:00:00Z",
        executor="local",
        failure_type="stage_exception",
        message="training input preparation failed",
        details=details,
        traceback_path="/worker/unavailable/traceback.log",
    )
    outer = ExecutionFailure(
        schema_version=1,
        run_uri="coordinator-run",
        stage_name="fit",
        attempt=1,
        failed_at="2020-01-01T00:00:00Z",
        executor="subprocess",
        failure_type="stage_exception",
        message="worker stage failed",
        details={"worker_failure": inner.to_dict()},
    )
    payload: dict[str, object] = {
        "owners": {
            "run_result": {
                "availability": "available",
                "failures": [outer.to_dict()],
            }
        }
    }

    class Result:
        def to_dict(self) -> dict[str, object]:
            return payload

    monkeypatch.setattr(LocalDaemonSocketClient, "admission", lambda *_args: Result())
    command = [
        "queue",
        "daemon-admission",
        "--endpoint",
        str(tmp_path / "absent.sock"),
        "admission",
    ]
    text_output, json_output = io.StringIO(), io.StringIO()
    assert main(command, stdout=text_output, stderr=io.StringIO()) == 0
    rendered = text_output.getvalue()
    assert "stage 'fit' failure: worker stage failed" in rendered
    assert "builtins.FileNotFoundError: missing /worker/data/product.json" in rendered
    assert "Prepare the product on the worker first." in rendered
    assert "cause:" in rendered
    assert (
        main([*command, "--format", "json"], stdout=json_output, stderr=io.StringIO())
        == 0
    )
    assert json.loads(json_output.getvalue())["result"] == payload


def test_queue_agent_reload_waits_for_rejected_receipt_and_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from loom.cli import queue as queue_cli
    from loom.queue import AgentControl, LocalDaemonSocketClient

    responses: Iterator[Mapping[str, object]] = iter(
        (
            {
                "operation_id": "reload-agent-1",
                "state": "pending_delivery",
                "code": None,
            },
            {
                "operation_id": "reload-agent-1",
                "state": "failed",
                "code": "reload_rejected",
            },
        )
    )
    seen: list[AgentControl] = []

    def control_agent(
        _client: LocalDaemonSocketClient, control: AgentControl
    ) -> Mapping[str, object]:
        seen.append(control)
        return next(responses)

    monkeypatch.setattr(LocalDaemonSocketClient, "control_agent", control_agent)
    monkeypatch.setattr(queue_cli, "_AGENT_RELOAD_RECEIPT_POLL_SECONDS", 0.0)
    stdout = io.StringIO()

    exit_code = main(
        [
            "queue",
            "daemon-agent-reload",
            "--endpoint",
            str(tmp_path / "daemon.sock"),
            "--operation-id",
            "reload-agent-1",
            "--agent-id",
            "agent-a",
            "--session-id",
            "session-a",
            "--config-revision",
            "config-1",
            "--format",
            "json",
        ],
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert exit_code != 0
    assert len(seen) == 2
    assert seen[0] == seen[1]
    assert json.loads(stdout.getvalue())["result"]["code"] == "reload_rejected"


def test_queue_agent_reload_timeout_while_applying_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from loom.cli import queue as queue_cli
    from loom.queue import LocalDaemonSocketClient

    monkeypatch.setattr(
        LocalDaemonSocketClient,
        "control_agent",
        lambda *_args, **_kwargs: {
            "operation_id": "reload-agent-applying",
            "state": "applying",
            "code": None,
        },
    )
    monkeypatch.setattr(queue_cli, "_AGENT_RELOAD_RECEIPT_WAIT_SECONDS", 0.0)

    exit_code = main(
        [
            "queue",
            "daemon-agent-reload",
            "--endpoint",
            str(tmp_path / "daemon.sock"),
            "--operation-id",
            "reload-agent-applying",
            "--agent-id",
            "agent-a",
            "--session-id",
            "session-a",
            "--config-revision",
            "config-1",
        ],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert exit_code != 0


def test_queue_scheduling_reload_rejection_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from loom.queue import CoordinatorSchedulingReload, LocalDaemonSocketClient

    seen: list[CoordinatorSchedulingReload] = []

    def reload_scheduling(
        _client: LocalDaemonSocketClient,
        request: CoordinatorSchedulingReload,
    ) -> Mapping[str, object]:
        seen.append(request)
        return {
            "operation_id": request.operation_id,
            "state": "failed",
            "code": "reload_rejected",
            "scheduling_epoch": request.expected_scheduling_epoch,
        }

    monkeypatch.setattr(LocalDaemonSocketClient, "reload_scheduling", reload_scheduling)
    stdout = io.StringIO()

    exit_code = main(
        [
            "queue",
            "daemon-scheduling-reload",
            "--endpoint",
            str(tmp_path / "daemon.sock"),
            "--operation-id",
            "reload-scheduling-1",
            "--expected-scheduling-epoch",
            "scheduling-epoch-1",
            "--format",
            "json",
        ],
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert exit_code != 0
    assert [item.operation_id for item in seen] == ["reload-scheduling-1"]
    assert json.loads(stdout.getvalue())["result"]["code"] == "reload_rejected"


def test_queue_scheduling_reload_applying_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from loom.queue import LocalDaemonSocketClient

    monkeypatch.setattr(
        LocalDaemonSocketClient,
        "reload_scheduling",
        lambda *_args, **_kwargs: {
            "operation_id": "reload-scheduling-applying",
            "state": "applying",
            "code": None,
            "scheduling_epoch": None,
        },
    )

    exit_code = main(
        [
            "queue",
            "daemon-scheduling-reload",
            "--endpoint",
            str(tmp_path / "daemon.sock"),
            "--operation-id",
            "reload-scheduling-applying",
            "--expected-scheduling-epoch",
            "scheduling-epoch-1",
        ],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert exit_code != 0


def _launch_profile() -> ResidentWorkerLaunchProfile:
    return ResidentWorkerLaunchProfile(
        project_root=Path.cwd(),
        python_executable=Path(sys.executable),
        descriptor=ResidentProfileDescriptor(
            "test-local", "v1", "test-project", "test-environment", "test-executor"
        ).to_dict(),
    )


def _queue_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "queue.yaml"
    config_path.write_text(
        f"""
        queue:
          service:
            db_path: {tmp_path / "queue.sqlite"}
          pools:
            - pool_name: gpu-pool
              mode: managed
          queues:
            - queue_name: gpu
              pool_name: gpu-pool
        """,
        encoding="utf-8",
    )
    return config_path


def _coordinator_service_config(tmp_path: Path) -> Path:
    agent_path = tmp_path / "local-agent.yaml"
    agent_path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "kind": "loom.local-agent-service",
                "agent_root": "deployment/agent",
                "resident_profiles": [
                    {
                        "descriptor": {
                            "profile_id": "test-local",
                            "revision": "v1",
                            "project_fingerprint": "test-project",
                            "environment_fingerprint": "test-environment",
                            "executor_fingerprint": "test-executor",
                        },
                        "project_root": str(Path.cwd()),
                        "python_executable": sys.executable,
                        "cpu_capacity": 1,
                        "memory_capacity_bytes": 0,
                        "gpu_devices": [],
                        "environment": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    agent_path.chmod(0o600)
    config_path = tmp_path / "coordinator.yaml"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "kind": "loom.coordinator-service",
                "deployment_root": "deployment",
                "run_store_root": "runs",
                "machine_id": "test-local",
                "poll_interval_seconds": 0.01,
                "max_accepted_time_step_seconds": 60,
                "local_agent": {"config": "local-agent.yaml", "env_file": None},
                "remote_profiles": [],
                "agent_policy": {
                    "revision": "policy-1",
                    "agents": [],
                    "principals": [],
                },
                "agent_server": None,
                "authority": {"kind": "embedded"},
            }
        ),
        encoding="utf-8",
    )
    config_path.chmod(0o600)
    return config_path


def _outbound_agent_service_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "agent.yaml"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "kind": "loom.outbound-agent-service",
                "agent_root": "remote-agent",
                "url": "https://localhost:8443",
                "server_ca_path": "ca.crt",
                "certificate_path": "agent.crt",
                "private_key_path": "agent.key",
                "resident_profiles": [
                    {
                        "descriptor": {
                            "profile_id": "test-remote",
                            "revision": "v1",
                            "project_fingerprint": "test-project",
                            "environment_fingerprint": "test-environment",
                            "executor_fingerprint": "test-executor",
                        },
                        "project_root": str(Path.cwd()),
                        "python_executable": sys.executable,
                        "cpu_capacity": 1,
                        "memory_capacity_bytes": 0,
                        "gpu_devices": [],
                        "environment": {},
                    }
                ],
                "registration": {
                    "config_revision": "config-1",
                    "inventory_revision": "inventory-1",
                    "availability_revision": "availability-1",
                    "pools": ["default"],
                    "capabilities": ["python"],
                },
                "reconnect_seconds": 0.1,
            }
        ),
        encoding="utf-8",
    )
    config_path.chmod(0o600)
    return config_path


def _enqueue(config_path: Path, queue_item_id: str) -> None:
    service = QueueService.from_spec(
        load_queue_spec(config_path),
        clock=_clock(
            "2020-01-01T00:00:00Z",
            "2020-01-01T00:00:01Z",
            "2020-01-01T00:00:02Z",
            "2020-01-01T00:00:03Z",
        ),
    )
    service.start()
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id=queue_item_id,
            queue_name="gpu",
            run_uri=f"file:///runs/{queue_item_id}",
        )
    )


def _clock(*values: str):
    remaining = list(values)

    def next_value() -> str:
        if len(remaining) == 1:
            return remaining[0]
        return remaining.pop(0)

    return next_value


def test_role_check_aggregates_findings_before_creating_deployment(
    tmp_path: Path,
) -> None:
    path = _coordinator_service_config(tmp_path)
    agent_path = tmp_path / "local-agent.yaml"
    payload = json.loads(agent_path.read_text(encoding="utf-8"))
    payload["resident_profiles"][0]["readiness"] = {
        "imports": ["does_not_exist"],
        "required_environment": ["LOOM_TEST_UNSET"],
    }
    agent_path.write_text(json.dumps(payload), encoding="utf-8")
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(
        ["queue", "daemon-check", str(path), "--format", "json"],
        stdout=stdout,
        stderr=stderr,
    )
    report = json.loads(stdout.getvalue())
    assert code == 3 and report["ok"] is False
    assert stderr.getvalue() == ""
    checks = report["result"]["checks"]
    assert {check["check_id"] for check in checks if check["status"] == "FAIL"} == {
        "packages.required_imports",
        "environment.worker",
    }
    assert (
        next(check for check in checks if check["check_id"] == "filesystem.role_roots")[
            "status"
        ]
        == "PASS"
    )
    assert set(report["result"]["groups"]) == {
        "config",
        "service",
        "python",
        "packages",
        "environment",
        "resources",
        "filesystem",
        "pipeline",
        "identity",
    }
    assert all(
        {"owner", "consequence", "repair", "applicability", "evidence"}
        <= check["details"].keys()
        for check in checks
    )
    assert not (tmp_path / "deployment").exists()
    assert str(tmp_path) not in stdout.getvalue()


def test_explicit_role_io_probe_preserves_existing_files(tmp_path: Path) -> None:
    path = _coordinator_service_config(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["local_agent"] = None
    path.write_text(json.dumps(payload), encoding="utf-8")
    roots = (tmp_path / "deployment", tmp_path / "runs")
    for root in roots:
        root.mkdir()
        (root / "keep").write_text("existing", encoding="utf-8")
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(
        ["queue", "daemon-check", str(path), "--probe-io", "--format", "json"],
        stdout=stdout,
        stderr=stderr,
    )
    assert code == 0 and stderr.getvalue() == ""
    checks = json.loads(stdout.getvalue())["result"]["checks"]
    io_checks = [check for check in checks if check["check_id"] == "filesystem.io"]
    assert len(io_checks) == 2 and all(check["status"] == "PASS" for check in io_checks)
    for root in roots:
        assert [item.name for item in root.iterdir()] == ["keep"]
        assert (root / "keep").read_text(encoding="utf-8") == "existing"


@pytest.mark.parametrize("command", ("agent-check", "daemon-check"))
def test_role_gpu_probe_cli_reports_cpu_inapplicability(
    tmp_path: Path, command: str
) -> None:
    path = (
        _outbound_agent_service_config(tmp_path)
        if command == "agent-check"
        else _coordinator_service_config(tmp_path)
    )
    if command == "daemon-check":
        payload = json.loads(path.read_text())
        payload["local_agent"] = None
        path.write_text(json.dumps(payload))
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(
        ["queue", command, str(path), "--probe-gpu", "--format", "json"],
        stdout=stdout,
        stderr=stderr,
    )
    assert code == 0 and stderr.getvalue() == ""
    checks = json.loads(stdout.getvalue())["result"]["checks"]
    check = next(item for item in checks if item["check_id"] == "resources.gpu_compute")
    assert check["status"] == "SKIP"
    assert check["details"]["applicability"] == "inapplicable"
