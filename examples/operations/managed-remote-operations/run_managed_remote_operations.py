"""Run guarded remote controls and restart the agent during supervised work."""

from __future__ import annotations

import json
import shutil
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
    coordinator_config, coordinator_environment, agent_config, agent_environment = (
        _copy_role_inputs(root, credentials, port)
    )
    readiness = recorder.cli(
        "queue", "agent-check", str(agent_config), "--env-file", str(agent_environment)
    )
    descriptor = next(
        check["details"]["evidence"]["descriptor"]
        for check in cast(list[dict[str, Any]], readiness["checks"])
        if check["check_id"] == "execution.identity"
    )
    _record_observed_remote_profile(
        coordinator_config,
        descriptor,
        certificate_fingerprint(credentials["agent"].with_suffix(".crt")),
    )
    recorder.cli(
        "queue",
        "daemon-check",
        str(coordinator_config),
        "--env-file",
        str(coordinator_environment),
    )
    recorder.cli(
        "queue",
        "daemon-init",
        str(coordinator_config),
        "--env-file",
        str(coordinator_environment),
    )
    recorder.cli(
        "queue", "agent-init", str(agent_config), "--env-file", str(agent_environment)
    )
    _require_passing_io_probe(
        recorder.cli(
            "queue",
            "agent-check",
            str(agent_config),
            "--env-file",
            str(agent_environment),
            "--probe-io",
        )
    )
    requirement = ExecutionRequirement(
        descriptor["project_fingerprint"],
        descriptor["environment_fingerprint"],
        descriptor["executor_fingerprint"],
    )
    service = load_coordinator_service_config(
        coordinator_config, env_file=coordinator_environment
    )
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
    daemon = recorder.start_cli(
        "queue",
        "daemon-serve",
        str(coordinator_config),
        "--env-file",
        str(coordinator_environment),
    )
    agent = None
    run_submitted = False
    completed = None
    try:
        status = wait_until(
            lambda: _running_daemon_status(recorder, daemon, endpoint), timeout=15
        )
        agent = recorder.start_cli(
            "queue",
            "agent-serve",
            str(agent_config),
            "--env-file",
            str(agent_environment),
        )
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
            agent = recorder.start_cli(
                "queue",
                "agent-serve",
                str(agent_config),
                "--env-file",
                str(agent_environment),
            )

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
                            "queue",
                            "agent-serve",
                            str(agent_config),
                            "--env-file",
                            str(agent_environment),
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
        io_probe="PASS",
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


def _copy_role_inputs(
    root: Path, credentials: dict[str, Path], port: int
) -> tuple[Path, Path, Path, Path]:
    """Copy templates, then provide protected role-local machine values."""

    here = Path(__file__).resolve().parent
    for name in ("coordinator.yaml", "agent.yaml"):
        destination = root / name
        shutil.copyfile(here / f"{name}.example", destination)
        destination.chmod(0o600)

    coordinator_environment = root / "coordinator.env"
    _write_environment(
        coordinator_environment,
        {
            "LOOM_DEPLOYMENT_ROOT": str(root / "deployment"),
            "LOOM_RUN_STORE_ROOT": str(root / "runs"),
            "LOOM_MACHINE_ID": "local-machine",
            "LOOM_AGENT_HOST": "localhost",
            "LOOM_AGENT_PORT": str(port),
            "LOOM_SERVER_CERTIFICATE": str(credentials["server"].with_suffix(".crt")),
            "LOOM_SERVER_PRIVATE_KEY": str(credentials["server"].with_suffix(".key")),
            "LOOM_CLIENT_CA": str(credentials["ca"].with_suffix(".crt")),
        },
    )
    agent_environment = root / "agent.env"
    _write_environment(
        agent_environment,
        {
            "LOOM_AGENT_ROOT": str(root / "outbound-agent"),
            "LOOM_COORDINATOR_URL": f"https://localhost:{port}",
            "LOOM_SERVER_CA": str(credentials["ca"].with_suffix(".crt")),
            "LOOM_AGENT_CERTIFICATE": str(credentials["agent"].with_suffix(".crt")),
            "LOOM_AGENT_PRIVATE_KEY": str(credentials["agent"].with_suffix(".key")),
            "LOOM_PROJECT_ROOT": str(Path(__file__).resolve().parent),
            "LOOM_PYTHON": str(Path(sys.executable).absolute()),
        },
    )
    return (
        root / "coordinator.yaml",
        coordinator_environment,
        root / "agent.yaml",
        agent_environment,
    )


def _record_observed_remote_profile(
    coordinator_config: Path, descriptor: dict[str, object], certificate: str
) -> None:
    source = coordinator_config.read_text(encoding="utf-8")
    profile_placeholder = "remote_profiles: []"
    credential_placeholder = "credential_fingerprints: {}"
    if (
        source.count(profile_placeholder) != 1
        or source.count(credential_placeholder) != 1
    ):
        raise RuntimeError("remote coordinator template has no observation slots")
    write_protected(
        coordinator_config,
        source.replace(
            profile_placeholder, f"remote_profiles: {json.dumps([descriptor])}"
        ).replace(
            credential_placeholder,
            "credential_fingerprints:\n"
            f"    {json.dumps(certificate)}: remote-agent-certificate",
        ),
    )


def _write_environment(path: Path, values: dict[str, str]) -> None:
    template = Path(__file__).parent / f"{path.name}.example"
    lines = template.read_text(encoding="utf-8").splitlines()
    remaining = dict(values)
    for index, line in enumerate(lines):
        key, separator, _ = line.partition("=")
        if separator and key in remaining:
            lines[index] = f"{key}={json.dumps(remaining.pop(key))}"
    if remaining:
        raise RuntimeError("role environment template is missing a machine input")
    write_protected(path, "\n".join(lines) + "\n")


def _require_passing_io_probe(report: dict[str, object]) -> None:
    checks = report.get("checks")
    if not isinstance(checks, list):
        raise RuntimeError("IO probe report has no checks")
    io_checks = [
        check
        for check in checks
        if isinstance(check, dict) and check.get("check_id") == "filesystem.io"
    ]
    if not io_checks or any(check.get("status") != "PASS" for check in io_checks):
        raise RuntimeError("copied remote role inputs did not pass the IO probe")


if __name__ == "__main__":
    main()
