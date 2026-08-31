"""Run the copyable embedded managed-local starter lifecycle."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

from loom.pipeline.stores import LocalRunStore
from loom.queue import prepare_managed_local_run


HERE = Path(__file__).resolve().parent


def main() -> None:
    root = _example_root()
    config = _write_service_config(root)
    endpoint = root / "deployment" / "coordinator" / "daemon.sock"
    _run_cli("queue", "daemon-init", str(config))
    receipt = prepare_managed_local_run(config, HERE / "pipeline.yaml", "starter-run")
    if (
        prepare_managed_local_run(config, HERE / "pipeline.yaml", "starter-run")
        != receipt
    ):
        raise RuntimeError("matching preparation replay changed the run identity")

    started_pids: set[int] = set()
    first = _start_service(config, started_pids)
    try:
        started = _wait_for_status(endpoint)
        submitted = _run_cli(
            "queue",
            "daemon-submit",
            "--endpoint",
            str(endpoint),
            "starter-run",
            receipt.run_uri,
        )
        completed = _run_cli(
            "queue",
            "daemon-wait",
            "--endpoint",
            str(endpoint),
            "starter-run",
            "--timeout",
            "15",
        )
        inspected = _run_cli(
            "inspect-run", receipt.run_uri, "--endpoint", str(endpoint)
        )
        if (
            completed.get("state") != "SUCCEEDED"
            or inspected.get("run_uri") != receipt.run_uri
        ):
            raise RuntimeError("managed-local starter run did not complete and inspect")
        if _report_text(receipt.run_uri, root / "runs") != "consumed {'value': 42}":
            raise RuntimeError("managed-local starter artifact contents are unexpected")
    finally:
        _stop_service(first)

    second = _start_service(config, started_pids)
    try:
        restarted = _wait_for_status(endpoint)
        retained = _run_cli(
            "queue",
            "daemon-admission",
            "--endpoint",
            str(endpoint),
            str(submitted["admission_id"]),
        )
        admission = retained.get("admission")
        if (
            restarted.get("coordinator_id") != started.get("coordinator_id")
            or restarted.get("coordinator_epoch") == started.get("coordinator_epoch")
            or not isinstance(admission, dict)
            or admission.get("state") != "SUCCEEDED"
        ):
            raise RuntimeError(
                "restart did not preserve the terminal managed admission"
            )
    finally:
        _stop_service(second)

    _assert_dead(started_pids)
    print(
        "journey_result: "
        + json.dumps(
            {
                "surfaces": [
                    "cli:inspect-run",
                    "cli:queue daemon-admission",
                    "cli:queue daemon-init",
                    "cli:queue daemon-serve",
                    "cli:queue daemon-status",
                    "cli:queue daemon-submit",
                    "cli:queue daemon-wait",
                    "python:prepare_managed_local_run",
                ],
                "started_pids": sorted(started_pids),
                "coordinator_id": started["coordinator_id"],
                "status": "SUCCEEDED",
                "restarted": True,
                "root": str(root),
            },
            sort_keys=True,
        )
    )


def _example_root() -> Path:
    output = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", tempfile.gettempdir()))
    output.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="managed-local-basic-", dir=output)).resolve()


def _write_service_config(root: Path) -> Path:
    config = root / "coordinator-service.yaml"
    resident_python = root / "resident-python"
    resident_python.write_text(
        f'#!/bin/sh\nexec "{Path(sys.executable)}" "$@"\n', encoding="utf-8"
    )
    resident_python.chmod(0o700)
    config.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "kind": "loom.coordinator-service",
                "deployment_root": "deployment",
                "run_store_root": "runs",
                "machine_id": "starter-machine",
                "poll_interval_seconds": 0.01,
                "max_accepted_time_step_seconds": 60,
                "embedded_profile": {
                    "descriptor": {
                        "profile_id": "starter-local",
                        "revision": "v1",
                        "project_fingerprint": "managed-local-basic",
                        "environment_fingerprint": "managed-local-basic",
                        "executor_fingerprint": "local",
                    },
                    "project_root": str(HERE),
                    "python_executable": str(resident_python),
                    "cpu_capacity": 1,
                    "memory_capacity_bytes": 0,
                    "gpu_devices": [],
                    "environment": {},
                },
                "remote_profiles": [],
                "agent_policy": {
                    "revision": "starter-1",
                    "agents": [],
                    "principals": [],
                },
                "agent_server": None,
                "authority": {"kind": "embedded"},
            }
        ),
        encoding="utf-8",
    )
    config.chmod(0o600)
    return config


def _run_cli(*args: str) -> dict[str, object]:
    result = subprocess.run(
        [_loom_cli(), *args, "--format", "json"],
        cwd=HERE,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Loom CLI failed: {' '.join(args)}\n{result.stderr}")
    envelope = json.loads(result.stdout)
    payload = envelope.get("result") if isinstance(envelope, dict) else None
    if (
        not isinstance(envelope, dict)
        or envelope.get("ok") is not True
        or not isinstance(payload, dict)
    ):
        raise RuntimeError(f"Loom CLI returned an invalid envelope: {result.stdout}")
    return payload


def _start_service(config: Path, started_pids: set[int]) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        [_loom_cli(), "queue", "daemon-serve", str(config), "--format", "json"],
        cwd=HERE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    started_pids.add(process.pid)
    return process


def _wait_for_status(endpoint: Path) -> dict[str, object]:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            return _run_cli("queue", "daemon-status", "--endpoint", str(endpoint))
        except RuntimeError:
            time.sleep(0.05)
    raise RuntimeError("managed-local daemon did not become ready")


def _stop_service(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        os.kill(process.pid, signal.SIGINT)
    try:
        _, stderr = process.communicate(timeout=15)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait(timeout=3)
        raise RuntimeError("managed-local daemon did not stop") from exc
    if process.returncode not in {0, 130, -signal.SIGINT}:
        raise RuntimeError(f"managed-local daemon failed while stopping: {stderr}")


def _report_text(run_uri: str, run_root: Path) -> str:
    report = (
        LocalRunStore(run_root).local_artifact_root(run_uri) / "consume" / "report.txt"
    )
    return report.read_text(encoding="utf-8")


def _assert_dead(pids: set[int]) -> None:
    for pid in pids:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        raise RuntimeError(f"managed-local service process still exists: {pid}")


def _loom_cli() -> str:
    executable = Path(sys.executable).with_name("loom")
    if not executable.is_file():
        raise RuntimeError("the installed Loom CLI is unavailable")
    return str(executable)


if __name__ == "__main__":
    main()
