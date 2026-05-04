"""Run the local pipeline example twice to demonstrate same-run resume."""

from __future__ import annotations

import os
from pathlib import Path

from loom.config import compose_config
from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.stores import LocalRunStore
from loom.timestamps import safe_timestamp_for_path


HERE = Path(__file__).resolve().parent


def main() -> None:
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", HERE / "runs"))
    run_id = f"local-example-{safe_timestamp_for_path(timespec='seconds')}"

    composed = compose_config(HERE / "pipeline.yaml")
    runner = PipelineRunner(run_store=LocalRunStore(run_root))

    first = runner.run(RunRequest(config=composed, run_id=run_id))
    second = runner.run(
        RunRequest(config=composed, run_id=run_id, open_existing=True)
    )

    print(f"run_dir: {first.run_dir}")
    print(f"first_status: {first.status.name}")
    print("first_stage_actions:")
    for stage_name, result in first.stage_results.items():
        print(f"  {stage_name}: {result.action.value}")

    print(f"resume_status: {second.status.name}")
    print("resume_stage_actions:")
    for stage_name, result in second.stage_results.items():
        print(f"  {stage_name}: {result.action.value}")

    print("artifacts:")
    for key, ref in sorted(second.artifact_index.items()):
        print(f"  {key}: {ref.uri}")


if __name__ == "__main__":
    main()

