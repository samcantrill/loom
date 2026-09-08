"""Run a persisted dependency-ordered pipeline through the local daemon."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import sys
import tempfile

from loom.artifacts import ArtifactRef
from loom.pipeline.context import StageContext
from loom.pipeline.stores import LocalRunStore
from loom.queue import (
    LocalDaemon,
    LocalDaemonAdmissionRequest,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    prepare_managed_local_run,
)
from loom.queue.deployment import load_coordinator_service_config


HERE = Path(__file__).resolve().parent


class ProduceStage:
    def run(
        self, context: StageContext, inputs: Mapping[str, ArtifactRef]
    ) -> Mapping[str, ArtifactRef]:
        del inputs
        return {
            "data": context.save_artifact(
                "data",
                {"value": 42},
                artifact_type="json",
                codec_key="json.v1",
            )
        }


class ConsumeStage:
    def run(
        self, context: StageContext, inputs: Mapping[str, ArtifactRef]
    ) -> Mapping[str, ArtifactRef]:
        del inputs
        value = context.load_input("data", expected_type="json")
        return {
            "report": context.save_artifact(
                "report",
                f"consumed {value}",
                artifact_type="text",
                codec_key="text.v1",
            )
        }


def main() -> None:
    output_root = Path(
        os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", tempfile.gettempdir())
    )
    output_root.mkdir(parents=True, exist_ok=True)
    example_root = Path(tempfile.mkdtemp(prefix="run-", dir=output_root))
    run_root = example_root / "runs"
    coordinator_config = _write_service_config(example_root)
    config = load_coordinator_service_config(coordinator_config).daemon
    LocalDaemon.initialize_deployment(config)
    receipt = prepare_managed_local_run(
        coordinator_config, HERE / "pipeline.yaml", "embedded-example"
    )
    replay = prepare_managed_local_run(
        coordinator_config, HERE / "pipeline.yaml", "embedded-example"
    )
    if replay != receipt:
        raise RuntimeError("identical preparation changed the run receipt")
    daemon = LocalDaemon(config)
    started = daemon.start()
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("example-client", LocalDaemonRole.CLIENT)
        )
        client.submit(LocalDaemonAdmissionRequest("example-run", receipt.run_uri))
        completed = client.wait("example-run", timeout_seconds=15)
    finally:
        daemon.stop()

    report = (
        LocalRunStore(run_root).local_artifact_root(receipt.run_uri)
        / "consume"
        / "report.txt"
    ).read_text(encoding="utf-8")
    if completed.state.value != "SUCCEEDED" or report != "consumed {'value': 42}":
        raise RuntimeError("embedded pipeline did not produce the expected report")

    print("managed_local_daemon:")
    print(f"  coordinator: {started.coordinator_id}")
    print(f"  status: {completed.state.value}")
    print("  stages: produce,consume")
    print("  admissions: 1")
    print(f"  preparation_replayed: {receipt == replay}")
    print(f"  report: {report}")
    print(f"  run_uri: {receipt.run_uri}")
    print(f"  root: {example_root}")


def _write_service_config(root: Path) -> Path:
    config = root / "coordinator-service.yaml"
    agent = root / "agent-service.yaml"
    agent.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "kind": "loom.local-agent-service",
                "agent_root": "deployment/agent",
                "resident_profiles": [
                    {
                        "descriptor": {
                            "profile_id": "embedding-local",
                            "revision": "v1",
                        },
                        "project_root": str(HERE),
                        "python_executable": str(Path(sys.executable).absolute()),
                        "cpu_capacity": 1,
                        "memory_capacity_bytes": 0,
                        "gpu_devices": [],
                        "environment": {},
                        "readiness": {
                            "imports": ["loom", "run_managed_local_queue"],
                            "import_roots": {"run_managed_local_queue": "."},
                            "source_roots": ["run_managed_local_queue.py"],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    agent.chmod(0o600)
    config.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "kind": "loom.coordinator-service",
                "deployment_root": "deployment",
                "run_store_root": "runs",
                "machine_id": "embedding-machine",
                "poll_interval_seconds": 0.01,
                "max_accepted_time_step_seconds": 60,
                "local_agent": {"config": "agent-service.yaml", "env_file": None},
                "remote_profiles": [],
                "agent_policy": {
                    "revision": "embedding-1",
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


if __name__ == "__main__":
    main()
