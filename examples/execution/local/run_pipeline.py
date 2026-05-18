"""Run the local pipeline example twice to demonstrate same-run resume."""

from __future__ import annotations

# ruff: noqa: E402

import os
from pathlib import Path
import sys

REPO_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "examples" / "support.py").is_file()
)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loom.config import compose_config
from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.stores import path_to_run_uri
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.timestamps import safe_timestamp_for_path


HERE = Path(__file__).resolve().parent


def main() -> None:
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    run_uri = path_to_run_uri(
        run_root / f"local-example-{safe_timestamp_for_path(timespec='seconds')}"
    )

    composed = compose_config(HERE / "pipeline.yaml")
    runner = PipelineRunner(
        run_store=create_authority_backed_serial_run_store(
            run_root,
            authority_store=SQLitePerRunAuthorityStore(),
        )
    )

    first = runner.run(RunRequest(config=composed, run_uri=run_uri))
    second = runner.run(
        RunRequest(config=composed, run_uri=run_uri, open_existing=True)
    )

    print(f"run_uri: {first.run_uri}")
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
