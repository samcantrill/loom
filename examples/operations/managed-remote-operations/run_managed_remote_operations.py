"""Run authenticated remote discovery and guarded controls through the CLI."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, cast

from loom.queue import ExecutionRequirement, prepare_managed_run
from loom.queue.deployment import load_coordinator_service_config
from weave import compose_config

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
    receipt = recorder.python(
        "prepare_managed_run",
        lambda: _prepare_remote_cpu_run(coordinator_config, coordinator_environment),
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
        submitted = recorder.cli(
            "queue",
            "daemon-submit",
            "--endpoint",
            str(endpoint),
            "remote-cpu-run",
            receipt.run_uri,
        )
        completed = recorder.cli(
            "queue",
            "daemon-wait",
            "--endpoint",
            str(endpoint),
            "remote-cpu-run",
            "--timeout",
            "15",
        )
        if completed.get("state") != "SUCCEEDED":
            raise RuntimeError("authenticated remote CPU run did not complete")
        inspected = recorder.cli(
            "inspect-run", receipt.run_uri, "--endpoint", str(endpoint)
        )
        if inspected.get("summary") != "SUCCEEDED" or inspected.get("stages") != [
            {
                "stage_name": "produce",
                "state": "SUCCEEDED",
                "attempt": None,
                "code": None,
            }
        ]:
            raise RuntimeError("remote CPU run is not inspectably complete")
        if _report_text(root / "outbound-agent") != "remote CPU artifact":
            raise RuntimeError("authenticated remote CPU artifact is unexpected")
        if not isinstance(submitted.get("admission_id"), str):
            raise RuntimeError("authenticated remote submission has no admission ID")

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
        cpu_artifact="remote CPU artifact",
        final_operation="example-remote-resume",
        io_probe="PASS",
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


def _prepare_remote_cpu_run(coordinator_config: Path, environment: Path):
    service = load_coordinator_service_config(coordinator_config, env_file=environment)
    if len(service.daemon.remote_profiles) != 1:
        raise RuntimeError("remote coordinator has no observed execution profile")
    descriptor = service.daemon.remote_profiles[0]
    requirement = ExecutionRequirement(
        descriptor.project_fingerprint,
        descriptor.environment_fingerprint,
        descriptor.executor_fingerprint,
    )
    return prepare_managed_run(
        service,
        compose_config(Path(__file__).resolve().parent / "pipeline.yaml"),
        "remote-cpu-run",
        execution_requirements={"produce": requirement},
    )


def _report_text(agent_root: Path) -> str:
    reports = tuple(agent_root.glob("assignments/*/artifacts/produce/report.txt"))
    if len(reports) != 1:
        raise RuntimeError("remote CPU artifact was not retained exactly once")
    return reports[0].read_text(encoding="utf-8")


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
