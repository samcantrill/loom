"""Observe committed event records with direct, instance-local sink registration."""

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

from examples.support import started_authority_session
from weave import compose_config
from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.event_sinks import EventSinkContext, EventSinkRegistry
from loom.pipeline.events import EventReference, PipelineEventRecord
from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.status import RunStatus
from loom.pipeline.stores import path_to_run_uri


HERE = Path(__file__).resolve().parent


def main() -> None:
    sys.path.insert(0, str(HERE))
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE / "outputs"))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    run_uri = path_to_run_uri(run_root / f"event-sink-{uuid4().hex[:8]}")
    registry = EventSinkRegistry()
    observed: list[str] = []

    def capture(event: PipelineEventRecord | EventReference, context: EventSinkContext) -> None:
        assert isinstance(event, PipelineEventRecord)
        if event.event_type == "run.started":
            status = store.read_run_status(context.run_uri)
            if status is None or status.status is not RunStatus.RUNNING:
                raise RuntimeError("run.started was not committed before observation")
        observed.append(event.event_type)

    def fail_completed(event: PipelineEventRecord | EventReference, context: EventSinkContext) -> None:
        _ = context
        if isinstance(event, PipelineEventRecord) and event.event_type == "run.completed":
            raise RuntimeError("intentional observer failure")

    registry.register("example.capture", capture)
    registry.register("example.fail_completed", fail_completed)
    with started_authority_session(output_root) as authority:
        store = create_authority_backed_serial_run_store(
            run_root, authority_config=authority.authority_config
        )
        result = PipelineRunner(run_store=store).run(
            RunRequest(
                config=compose_config(HERE / "pipeline.yaml"),
                run_uri=run_uri,
                event_sink_registry=registry,
            )
        )
        failures = store.read_event_sink_failures(run_uri)
        required = {"run.started", "stage.completed", "run.completed"}
        if result.status is not RunStatus.SUCCEEDED or not required <= set(observed):
            raise RuntimeError("required lifecycle events were not observed")
        if len(failures) != 1 or failures[0].sink_name != "example.fail_completed":
            raise RuntimeError("expected exactly one retained observer failure")

    print("event_sink:")
    print(f"  run_uri: {run_uri}")
    print(f"  run_status: {result.status.name}")
    print(f"  observed_events: {','.join(observed)}")
    print(f"  failure_count: {len(failures)}")
    print(f"  failure_sink: {failures[0].sink_name}")


if __name__ == "__main__":
    main()
