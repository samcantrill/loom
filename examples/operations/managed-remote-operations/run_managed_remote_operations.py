"""Run authenticated remote discovery and guarded controls through the CLI."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, cast


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
    checkout = Path(__file__).resolve().parents[3]
    coordinator_config, coordinator_environment, agent_config, agent_environment = (
        _copy_role_inputs(root, credentials, checkout, port)
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


def _copy_role_inputs(
    root: Path, credentials: dict[str, Path], checkout: Path, port: int
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
            "LOOM_PROJECT_ROOT": str(checkout),
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
    write_protected(path, "".join(f"{key}={value}\n" for key, value in values.items()))


if __name__ == "__main__":
    main()
