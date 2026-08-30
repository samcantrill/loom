"""Run authenticated remote discovery and guarded controls through the CLI."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


OPERATIONS_ROOT = Path(__file__).resolve().parents[1]
if str(OPERATIONS_ROOT) not in sys.path:
    sys.path.insert(0, str(OPERATIONS_ROOT))

from _managed_journey_support import (  # noqa: E402
    JourneyRecorder,
    assert_processes_dead,
    available_port,
    certificate_fingerprint,
    example_root,
    generate_mutual_tls,
    stop_cli_service,
    wait_until,
    write_protected,
)


def main() -> None:
    recorder = JourneyRecorder()
    root = example_root("managed-remote-operations")
    credentials = generate_mutual_tls(root / "tls")
    port = available_port()
    coordinator_config = root / "coordinator.yaml"
    agent_config = root / "agent.yaml"
    checkout = Path(__file__).resolve().parents[3]
    write_protected(
        coordinator_config,
        _coordinator_yaml(
            root,
            checkout,
            port,
            certificate_fingerprint(credentials["agent"].with_suffix(".crt")),
        ),
    )
    write_protected(agent_config, _agent_yaml(root, checkout, port))
    recorder.cli("queue", "daemon-init", str(coordinator_config))
    recorder.cli("queue", "agent-init", str(agent_config))

    endpoint = root / "deployment" / "coordinator" / "daemon.sock"
    daemon = recorder.start_cli("queue", "daemon-serve", str(coordinator_config))
    agent = None
    try:
        status = wait_until(
            lambda: _running_daemon_status(recorder, daemon, endpoint), timeout=15
        )
        agent = recorder.start_cli("queue", "agent-serve", str(agent_config))
        projection = wait_until(
            lambda: _available_agent(recorder, daemon, endpoint), timeout=20
        )
        recorder.observe_process_tree(daemon.pid, agent.pid)
        detail = recorder.cli(
            "queue", "daemon-agent", "--endpoint", str(endpoint), "machine-B"
        )
        if detail["session_id"] != projection["session_id"]:
            raise RuntimeError("agent detail did not preserve the discovered session fence")

        drain = recorder.cli(
            "queue",
            "daemon-agent-drain",
            "--endpoint",
            str(endpoint),
            "--operation-id",
            "example-remote-drain",
            "--agent-id",
            "machine-B",
            "--session-id",
            str(detail["session_id"]),
            "--config-revision",
            str(detail["config_revision"]),
            "--pool",
            "default",
            "--reason",
            "example-maintenance",
        )
        drained = recorder.cli(
            "queue",
            "daemon-operation-wait",
            "--endpoint",
            str(endpoint),
            "example-remote-drain",
            "--timeout",
            "15",
        )
        operation = recorder.cli(
            "queue",
            "daemon-operation",
            "--endpoint",
            str(endpoint),
            "example-remote-drain",
        )
        if drain["state"] not in {"pending_delivery", "applied"}:
            raise RuntimeError("guarded drain was not durably accepted")
        if drained["kind"] != "TERMINAL" or operation["state"] != "applied":
            raise RuntimeError("remote agent did not apply the guarded drain")

        resume = recorder.cli(
            "queue",
            "daemon-agent-resume",
            "--endpoint",
            str(endpoint),
            "--operation-id",
            "example-remote-resume",
            "--agent-id",
            "machine-B",
            "--session-id",
            str(detail["session_id"]),
            "--config-revision",
            str(detail["config_revision"]),
            "--pool",
            "default",
            "--reason",
            "example-maintenance-complete",
        )
        resumed = recorder.cli(
            "queue",
            "daemon-operation-wait",
            "--endpoint",
            str(endpoint),
            "example-remote-resume",
            "--timeout",
            "15",
        )
        if resume["state"] not in {"pending_delivery", "applied"} or resumed[
            "kind"
        ] != "TERMINAL":
            raise RuntimeError("remote agent did not apply the guarded resume")
    finally:
        try:
            if agent is not None:
                recorder.observe_process_tree(agent.pid)
                stop_cli_service(agent)
        finally:
            recorder.observe_process_tree(daemon.pid)
            stop_cli_service(daemon)
    assert_processes_dead(recorder.started_pids)
    recorder.emit(
        authenticated=True,
        coordinator_id=status["coordinator_id"],
        agent_id="machine-B",
        final_operation="example-remote-resume",
        root=str(root),
    )


def _running_daemon_status(
    recorder: JourneyRecorder, process: subprocess.Popen[str], endpoint: Path
) -> dict[str, object] | None:
    if process.poll() is not None:
        stdout, stderr = process.communicate()
        raise RuntimeError(f"coordinator exited early\n{stdout}\n{stderr}")
    if not endpoint.exists():
        return None
    return recorder.cli("queue", "daemon-status", "--endpoint", str(endpoint))


def _available_agent(
    recorder: JourneyRecorder, process: subprocess.Popen[str], endpoint: Path
) -> dict[str, object] | None:
    if process.poll() is not None:
        stdout, stderr = process.communicate()
        raise RuntimeError(f"outbound agent exited early\n{stdout}\n{stderr}")
    page = recorder.cli(
        "queue", "daemon-agents", "--endpoint", str(endpoint), "--limit", "10"
    )
    agents = page.get("agents")
    if not isinstance(agents, list):
        raise RuntimeError("agent page is malformed")
    for item in agents:
        if isinstance(item, dict) and item.get("agent_id") == "machine-B":
            return item if item.get("available") is True else None
    return None


def _coordinator_yaml(root: Path, checkout: Path, port: int, fingerprint: str) -> str:
    return f"""
schema_version: 2
kind: loom.coordinator-service
deployment_root: {_quoted(root / 'deployment')}
run_store_root: {_quoted(root / 'runs')}
machine_id: local-machine
poll_interval_seconds: 0.05
max_accepted_time_step_seconds: 3600
authority:
  kind: embedded
embedded_profile:
  descriptor:
    profile_id: local-default
    revision: v1
    project_fingerprint: example-project-v1
    environment_fingerprint: example-environment-v1
    executor_fingerprint: local-executor-v1
  project_root: {_quoted(checkout)}
  python_executable: {_quoted(Path(sys.executable))}
  cpu_capacity: 1
  memory_capacity_bytes: 0
  gpu_devices: []
  environment: {{}}
remote_profiles:
  - profile_id: remote-default
    revision: v1
    project_fingerprint: example-project-v1
    environment_fingerprint: example-environment-v1
    executor_fingerprint: local-executor-v1
agent_policy:
  revision: policy-1
  agents:
    - credential_id: remote-agent-certificate
      principal_id: remote-agent-principal
      agent_id: machine-B
      pools: [default]
      capabilities: [python, remote-stage-execution-v3, regular-file-relay-v1]
      gpu_devices: []
  principals: []
  local_owner:
    actions: [drain, resume]
    agent_ids: [machine-B]
    pools: [default]
agent_server:
  host: localhost
  port: {port}
  certificate_path: {_quoted(root / 'tls' / 'server.crt')}
  private_key_path: {_quoted(root / 'tls' / 'server.key')}
  client_ca_path: {_quoted(root / 'tls' / 'ca.crt')}
  credential_fingerprints:
    {json.dumps(fingerprint)}: remote-agent-certificate
"""


def _agent_yaml(root: Path, checkout: Path, port: int) -> str:
    return f"""
schema_version: 2
kind: loom.outbound-agent-service
agent_root: {_quoted(root / 'outbound-agent')}
url: https://localhost:{port}
server_ca_path: {_quoted(root / 'tls' / 'ca.crt')}
certificate_path: {_quoted(root / 'tls' / 'agent.crt')}
private_key_path: {_quoted(root / 'tls' / 'agent.key')}
reconnect_seconds: 0.05
resident_profiles:
  - descriptor:
      profile_id: remote-default
      revision: v1
      project_fingerprint: example-project-v1
      environment_fingerprint: example-environment-v1
      executor_fingerprint: local-executor-v1
    project_root: {_quoted(checkout)}
    python_executable: {_quoted(Path(sys.executable))}
    cpu_capacity: 1
    memory_capacity_bytes: 0
    gpu_devices: []
    environment: {{}}
registration:
  config_revision: remote-config-v1
  inventory_revision: remote-inventory-v1
  availability_revision: remote-availability-v1
  pools: [default]
  capabilities: [python, remote-stage-execution-v3, regular-file-relay-v1]
"""


def _quoted(path: Path) -> str:
    return json.dumps(str(path.resolve()))


if __name__ == "__main__":
    main()
