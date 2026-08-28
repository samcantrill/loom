"""Run the manual Discord webhook event-sink example through direct Python wiring."""

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
HERE = Path(__file__).resolve().parent
PACKAGE_SOURCE = HERE / "src"
for path in (REPO_ROOT, PACKAGE_SOURCE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from examples.support import started_authority_session
from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.event_sinks import EventSinkRegistry
from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.status import RunStatus
from loom.pipeline.stores import path_to_run_uri
from loom_discord import discord_event_sink
from weave import compose_config


def main() -> None:
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE / "outputs"))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    run_uri = path_to_run_uri(run_root / f"discord-webhook-{uuid4().hex[:8]}")
    registration = discord_event_sink()
    registry = EventSinkRegistry()
    registry.register(
        "notifications.discord",
        registration.sink,
        subscription=registration.subscription,
    )
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
        notification_failures = store.read_event_sink_failures(run_uri)
    if result.status is not RunStatus.SUCCEEDED:
        raise RuntimeError(f"example run did not succeed: {result.status.name}")
    print(f"run_uri: {run_uri}")
    print(f"run_status: {result.status.name}")
    print(f"notification_failure_count: {len(notification_failures)}")
    print(
        "notification_status: "
        + ("accepted" if not notification_failures else "failed")
    )
    if notification_failures:
        raise RuntimeError(notification_failures[0].failure_message)


if __name__ == "__main__":
    main()
