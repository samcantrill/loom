"""Installed synthetic coordinator observer factories; never contact a network."""

import json
from pathlib import Path

from loom.pipeline.event_sinks import EventSinkRegistration
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore


def selected_capture(path: Path):
    """Select the installed capture factory without constructing its callback."""
    from loom.queue._lifecycle_observers import LifecycleObservers, parse_event_sinks

    return LifecycleObservers(
        parse_event_sinks(
            [{"name": "test.capture", "factory": {
                "_target_": "tests.support.lifecycle_observers.capture",
                "path": str(path),
            }}]
        )
    )


def captured_events(path: Path, run_uri: str):
    """Read callbacks for one exact run, excluding factory construction records."""
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    return [row["event"] for row in rows if row.get("event", {}).get("run_uri") == run_uri]


def capture(path: str, fail_completed: bool = False) -> EventSinkRegistration:
    with Path(path).open("a") as stream:
        stream.write(json.dumps({"constructed": True}) + "\n")

    def observe(event, context):
        snapshot = SQLitePerRunAuthorityStore(event.run_uri).open_run(event.run_uri)
        with Path(path).open("a") as stream:
            stream.write(
                json.dumps({"event": event.to_dict(), "status": snapshot.status.value})
                + "\n"
            )
        if fail_completed and event.event_type == "run.completed":
            raise RuntimeError("synthetic notification failure")

    return EventSinkRegistration(sink=observe)
