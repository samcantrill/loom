"""Installed example factories selected only by protected coordinator config."""

import json
from pathlib import Path

from loom.pipeline.event_sinks import EventSinkRegistration


def capture(path: str) -> EventSinkRegistration:
    def observe(event, context):
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event.to_dict()) + "\n")

    return EventSinkRegistration(sink=observe)


def fail_completed() -> EventSinkRegistration:
    def observe(event, context):
        if event.event_type == "run.completed":
            raise RuntimeError("intentional observer failure")

    return EventSinkRegistration(sink=observe)
