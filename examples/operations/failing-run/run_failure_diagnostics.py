"""Run a failing local pipeline and inspect diagnostics."""

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
from examples.support import run_cli_json

HERE = Path(__file__).resolve().parent


def main() -> None:
    sys.path.insert(0, str(HERE))
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    config = HERE / "pipeline.yaml"
    preflight = run_cli_json(["preflight", str(config), "--format", "json"])
    outcome = run_example(config, output_root)
    print_outcome(outcome)
    print(f"preflight_status: {preflight['result']['status']}")
    artifact_count = sum(
        len(record.outputs) for record in worker_records(outcome).values()
    )
    print(f"artifact_count: {artifact_count}")
    failures = [
        name
        for name, record in worker_records(outcome).items()
        if record.status.value == "FAILED"
    ]
    assert failures, "expected the authored stage failure"
    print(f"failed_stages: {','.join(failures)}")


if __name__ == "__main__":
    main()
