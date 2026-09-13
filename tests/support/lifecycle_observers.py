"""Installed synthetic coordinator observer factories; never contact a network."""

import json
from pathlib import Path

from loom.pipeline.event_sinks import EventSinkRegistration
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore


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
