"""Run guarded remote controls and restart the agent during supervised work."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Any, cast

from weave import compose_config

from loom.pipeline.stores import LocalArtifactStore, LocalRunStore
from loom.queue import ExecutionRequirement, prepare_managed_run
from loom.queue.deployment import load_coordinator_service_config


HERE = Path(__file__).resolve().parent
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
    write_protected(agent_config, _agent_yaml(root, HERE, port))
    readiness = recorder.cli("queue", "agent-check", str(agent_config))
    descriptor = next(
        check["details"]["evidence"]["descriptor"]
        for check in cast(list[dict[str, Any]], readiness["checks"])
        if check["check_id"] == "execution.identity"
    )
    write_protected(
        coordinator_config,
        _coordinator_yaml(
            root,
            descriptor,
            port,
            certificate_fingerprint(credentials["agent"].with_suffix(".crt")),
        ),
    )
    recorder.cli("queue", "daemon-init", str(coordinator_config))
    recorder.cli("queue", "agent-init", str(agent_config))
    requirement = ExecutionRequirement(
        descriptor["project_fingerprint"],
        descriptor["environment_fingerprint"],
        descriptor["executor_fingerprint"],
    )
    service = load_coordinator_service_config(coordinator_config)
    receipt = recorder.python(
        "prepare_managed_run",
        lambda: prepare_managed_run(
            service,
            compose_config(HERE / "pipeline.yaml"),
            "remote-lifecycle",
            execution_requirements={"work": requirement},
        ),
    )

    endpoint = root / "deployment" / "coordinator" / "daemon.sock"
    daemon = recorder.start_cli("queue", "daemon-serve", str(coordinator_config))
    agent = None
    run_submitted = False
    completed = None
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
            raise RuntimeError(
                "agent detail did not preserve the discovered session fence"
            )

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
        if (
            resume["state"] not in {"pending_delivery", "applied"}
            or resumed["kind"] != "TERMINAL"
        ):
            raise RuntimeError("remote agent did not apply the guarded resume")

        submitted = recorder.cli(
            "queue",
            "daemon-submit",
            "--endpoint",
            str(endpoint),
            "remote-lifecycle",
            receipt.run_uri,
        )
        run_submitted = True
        wait_until(
            lambda: _running_work(recorder, endpoint, receipt.run_uri), timeout=15
        )
        original_assignment = _assignment(
            recorder, endpoint, str(submitted["admission_id"])
        )
        recorder.observe_process_tree(daemon.pid, agent.pid)
        stop_cli_service(agent)
        stopped_returncode = agent.returncode
        try:
            retained = _running_work(recorder, endpoint, receipt.run_uri)
            retained_assignment = _assignment(
                recorder, endpoint, str(submitted["admission_id"])
            )
            if (
                retained is None
                or retained_assignment["attempt"] != original_assignment["attempt"]
                or retained_assignment["assignment_id"]
                != original_assignment["assignment_id"]
                or retained_assignment["claim_id"] != original_assignment["claim_id"]
                or retained_assignment["state"] == "released"
            ):
                raise RuntimeError(
                    "agent stop did not retain the active attempt and claim"
                )
        finally:
            agent = recorder.start_cli("queue", "agent-serve", str(agent_config))

        # Startup may join retained work before advertising normal availability.
        completed = _wait_for_run(recorder, endpoint)
        inspected = recorder.cli(
            "inspect-run", receipt.run_uri, "--endpoint", str(endpoint)
        )
        (finished,) = inspected["stages"]
        released = _assignment(recorder, endpoint, str(submitted["admission_id"]))
        if (
            completed["state"] != "SUCCEEDED"
            or finished["state"] != "SUCCEEDED"
            or released["attempt"] != original_assignment["attempt"]
            or released["assignment_id"] != original_assignment["assignment_id"]
            or released["claim_id"] != original_assignment["claim_id"]
            or released["state"] != "released"
        ):
            raise RuntimeError(
                "restarted agent did not complete and release the original assignment"
            )
        factory = service.daemon.coordinator_authority_factory
        if factory is None:
            raise RuntimeError(
                "the example requires its configured coordinator authority"
            )
        authority = factory(receipt.run_uri)
        snapshot = recorder.python(
            "CoordinatorAuthorityStore.open_run",
            lambda: authority.open_run(receipt.run_uri),
        )
        (stage,) = snapshot.stages
        (attempt,) = stage.attempts
        (fact,) = stage.artifact_facts
        if attempt.attempt != original_assignment["attempt"]:
            raise RuntimeError("the authority result belongs to a different attempt")
        artifacts = LocalArtifactStore(
            LocalRunStore(root / "runs").local_artifact_root(receipt.run_uri)
        )
        report = recorder.python(
            "LocalArtifactStore.load",
            lambda: artifacts.load(fact.artifact, expected_type="json"),
        )
        if report["value"] != 42:
            raise RuntimeError(
                "remote result relay returned unexpected artifact contents"
            )
        recorder.started_pids.add(report["worker_pid"])
    finally:
        try:
            try:
                # Even a failed continuity assertion must let bounded work settle.
                if run_submitted and completed is None:
                    if agent is None or agent.poll() is not None:
                        agent = recorder.start_cli(
                            "queue", "agent-serve", str(agent_config)
                        )
                    _wait_for_run(recorder, endpoint)
            finally:
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
        run_uri=receipt.run_uri,
        result=completed["state"],
        foreground_stop_returncode=stopped_returncode,
        retained_while_stopped=True,
        initial_attempt=original_assignment["attempt"],
        completed_attempt=attempt.attempt,
        assignment_id=released["assignment_id"],
        assignment_released=released["state"] == "released",
        report_value=report["value"],
        root=str(root),
    )


def _running_work(
    recorder: JourneyRecorder, endpoint: Path, run_uri: str
) -> dict[str, Any] | None:
    inspected = recorder.cli("inspect-run", run_uri, "--endpoint", str(endpoint))
    (stage,) = cast(list[dict[str, Any]], inspected["stages"])
    lifecycle = next(axis for axis in inspected["axes"] if axis["name"] == "lifecycle")
    if stage["state"] == "RUNNING" and lifecycle["state"] == "RUNNING":
        return stage
    return None


def _assignment(
    recorder: JourneyRecorder, endpoint: Path, admission_id: str
) -> dict[str, Any]:
    detail = recorder.cli(
        "queue", "daemon-admission", "--endpoint", str(endpoint), admission_id
    )
    (assignment,) = detail["owners"]["assignment"]["assignments"]
    return assignment


def _wait_for_run(recorder: JourneyRecorder, endpoint: Path) -> dict[str, object]:
    return recorder.cli(
        "queue",
        "daemon-wait",
        "--endpoint",
        str(endpoint),
        "remote-lifecycle",
        "--timeout",
        "25",
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


def _coordinator_yaml(
    root: Path, descriptor: dict[str, object], port: int, fingerprint: str
) -> str:
    return f"""
schema_version: 3
kind: loom.coordinator-service
deployment_root: {_quoted(root / "deployment")}
run_store_root: {_quoted(root / "runs")}
machine_id: local-machine
poll_interval_seconds: 0.05
max_accepted_time_step_seconds: 3600
authority:
  kind: embedded
local_agent: null
remote_profiles: {json.dumps([descriptor])}
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
  certificate_path: {_quoted(root / "tls" / "server.crt")}
  private_key_path: {_quoted(root / "tls" / "server.key")}
  client_ca_path: {_quoted(root / "tls" / "ca.crt")}
  credential_fingerprints:
    {json.dumps(fingerprint)}: remote-agent-certificate
"""


def _agent_yaml(root: Path, project: Path, port: int) -> str:
    return f"""
schema_version: 3
kind: loom.outbound-agent-service
agent_root: {_quoted(root / "outbound-agent")}
url: https://localhost:{port}
server_ca_path: {_quoted(root / "tls" / "ca.crt")}
certificate_path: {_quoted(root / "tls" / "agent.crt")}
private_key_path: {_quoted(root / "tls" / "agent.key")}
reconnect_seconds: 0.05
resident_profiles:
  - descriptor:
      profile_id: remote-default
      revision: v1
    project_root: {_quoted(project)}
    python_executable: {json.dumps(str(Path(sys.executable).absolute()))}
    cpu_capacity: 1
    memory_capacity_bytes: 0
    gpu_devices: []
    environment: {{}}
    readiness:
      imports: [loom, stages]
      import_roots: {{stages: .}}
      source_roots: [stages.py]
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
