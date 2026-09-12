"""Small protected local deployments used by the agent execution examples."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

import loom
from loom.coordinator import RunRequest
from loom.queue.preparation import PreparationSource, PrepareRunRequest


def run_example(
    config: Path, output_root: Path, *, container=None, run_options=None, overrides=()
):
    """Prepare and run importable project code, then settle owned services."""
    config = config.resolve()
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    # Unix service sockets need a short owned root; artifacts stay in output_root.
    root = Path(tempfile.mkdtemp(prefix="loom-example-"))
    profile = {
        "descriptor": {
            "profile_id": "installed",
            "revision": "v1",
            "project_fingerprint": "observe",
            "environment_fingerprint": "observe",
            "executor_fingerprint": "observe",
        },
        "project_root": str(config.parent),
        "python_executable": sys.executable,
        "cpu_capacity": 2,
        "memory_capacity_bytes": 8 * 1024**3,
        "gpu_devices": [],
        "environment": {
            "PYTHONPATH": str(config.parent)
            + os.pathsep
            + os.environ.get("PYTHONPATH", "")
        },
        "readiness": {"imports": ["loom", "weave", "stages"]},
        "preparation_shared_roots": {"project": str(root / "snapshots")},
    }
    if container is not None:
        profile["container"] = container
    agent = {
        "schema_version": 3,
        "kind": "loom.local-agent-service",
        "agent_root": "deployment/agent",
        "resident_profiles": [profile],
    }
    coordinator = {
        "schema_version": 3,
        "kind": "loom.coordinator-service",
        "deployment_root": "deployment",
        "run_store_root": str(
            Path(
                os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs")
            ).resolve()
        ),
        "machine_id": "example",
        "poll_interval_seconds": 0.05,
        "max_accepted_time_step_seconds": 60,
        "local_agent": {"config": "agent.json", "env_file": None},
        "remote_profiles": [],
        "agent_server": None,
        "agent_policy": {
            "revision": "v1",
            "agents": [],
            "principals": [],
            "local_owner": {
                "actions": ["scheduling_reload"],
                "agent_ids": [],
                "pools": [],
            },
        },
        "authority": {"kind": "embedded"},
        "preparation": {
            "source_roots": {
                "project": {
                    "path": str(config.parent),
                    "shared_snapshot_root": "snapshots",
                }
            },
            "profiles": {
                "example": {
                    "resident_profile_id": "installed",
                    "allowed_source_roots": ["project"],
                    "source_modes": ["shared"],
                    "runtime_options": {"executor": "local"},
                }
            },
        },
    }
    source = PreparationSource("shared", "project", ".", (config.name,))
    selection = {
        "schema_version": 1,
        "kind": "loom.deployment",
        "coordinator": {"service_config": "coordinator.json", "lifetime": "run"},
        "binding_path": "binding.json",
        "startup_seconds": 60,
        "preparation": {"source": source.to_dict(), "profile": "example"},
    }
    for name, value in (
        ("agent.json", agent),
        ("coordinator.json", coordinator),
        ("selection.json", selection),
    ):
        path = root / name
        path.write_text(json.dumps(value))
        path.chmod(0o600)
    preparation = PrepareRunRequest(
        root.name,
        root.name,
        source,
        config.name,
        "example",
        run_options=run_options or {},
        overrides=overrides,
    )
    result = loom.run(
        RunRequest(preparation, "example"), deployment=root / "selection.json"
    )
    if result.observation.admission is None:
        raise RuntimeError(
            f"example preparation failed: {result.observation.operation}"
        )
    if result.cleanup["coordinator"]["state"] != "stopped":
        raise RuntimeError("example coordinator did not finish owned cleanup")
    print(f"deployment_root: {root}")
    return result


def print_outcome(outcome):
    """Expose the ordinary native lifecycle and its separate cleanup result."""
    admission = outcome.observation.admission
    print(f"run_uri: {admission.run_uri}")
    print(f"run_status: {admission.state.value}")
    print(f"coordinator_cleanup: {outcome.cleanup['coordinator']['state']}")


def worker_records(outcome):
    """Read typed materialized results after native terminal settlement.

    These records describe outputs and diagnostics; the native admission remains
    the source of run success, and service cleanup has already completed.
    """
    from loom.io.uris import uri_to_path
    from loom.pipeline.execution.models import StageWorkerResult

    root = uri_to_path(outcome.observation.admission.run_uri)
    return {
        path.parent.name: StageWorkerResult.from_dict(
            json.loads(path.read_text())["worker_result"]
        )
        for path in (root / "stages").glob("*/worker_result.json")
    }
