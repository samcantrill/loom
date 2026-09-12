"""Run a failing Docker pipeline and inspect persisted diagnostics."""

from __future__ import annotations

# ruff: noqa: E402

import os
import sys
from pathlib import Path

REPO_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "examples" / "support.py").is_file()
)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from examples.execution.agent_workers import run_example, print_outcome, worker_records
from examples.execution.containers.docker.daemon_fixture import fake_docker

HERE = Path(__file__).resolve().parent


def main() -> None:
    sys.path.insert(0, str(HERE))
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    with fake_docker(output_root / "fake-daemon") as (binding, calls):
        binding["container"]["environment"] = {
            "variables": {"LOOM_CONTAINER_EXAMPLE": "docker-failure"}
        }
        outcome = run_example(
            HERE / "failing-pipeline.yaml",
            output_root,
            container=binding,
            overrides=("runtime.profile=null",),
        )
        print_outcome(outcome)
        workers = [
            call
            for call in calls
            if call[0] == "create" and "loom.queue._resident_stage_worker" in call
        ]
        assert workers
        print(f"fake_docker_call_count: {len(workers)}")
        print("runtime_qualification: local daemon fixture")
        artifact_count = sum(
            len(record.outputs) for record in worker_records(outcome).values()
        )
        print(f"artifact_count: {artifact_count}")


if __name__ == "__main__":
    main()
