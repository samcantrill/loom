"""Observe committed native lifecycle events from configured coordinator callbacks."""

from __future__ import annotations

# ruff: noqa: E402

import os
import sys
from pathlib import Path
from uuid import uuid4

REPO_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "examples" / "support.py").is_file()
)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from examples.execution.agent_workers import run_example
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore

HERE = Path(__file__).resolve().parent


def main() -> None:
    import json

    output_root = Path(
        os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE / "outputs")
    ).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    observed_path = output_root / f"observations-{uuid4().hex[:8]}.jsonl"
    os.environ["PYTHONPATH"] = str(HERE) + os.pathsep + os.environ.get("PYTHONPATH", "")
    result = run_example(
        HERE / "pipeline.yaml",
        output_root,
        event_sinks=[
            {
                "name": "example.capture",
                "factory": {
                    "_target_": "event_observers.capture",
                    "path": str(observed_path),
                },
            },
            {
                "name": "example.fail_completed",
                "factory": {
                    "_target_": "event_observers.fail_completed",
                },
            },
        ],
    )
    admission = result.observation.admission
    run_uri = admission.run_uri
    records = [json.loads(line) for line in observed_path.read_text().splitlines()]
    observed = [
        record["event_type"] for record in records if record["run_uri"] == run_uri
    ]
    failures = SQLitePerRunAuthorityStore(run_uri).read_event_sink_failures(run_uri)
    required = {"run.started", "stage.completed", "run.completed"}
    if admission.state.value != "SUCCEEDED" or not required <= set(observed):
        raise RuntimeError("required lifecycle events were not observed")
    if len(failures) != 1 or failures[0].sink_name != "example.fail_completed":
        raise RuntimeError("expected exactly one retained observer failure")
    print("event_sink:")
    print(f"  run_uri: {run_uri}")
    print(f"  run_status: {admission.state.value}")
    print(f"  observed_events: {','.join(observed)}")
    print(f"  failure_count: {len(failures)}")
    print(f"  failure_sink: {failures[0].sink_name}")


if __name__ == "__main__":
    main()
