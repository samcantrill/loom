"""Count- and byte-bounded relay of the existing assignment event journal."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from loom.serialization import PlainData, thaw_plain_data

from ._agent_session_codec import _MAX_BATCH_EVENTS, _MAX_BODY_BYTES, _exact, _integer, _string
from ._agent_session_journal import _canonical_digest, _canonical_json
from .agent_sessions import AgentSessionView
from .errors import QueueConflictError, QueueServiceError


def pack_event_batch(
    session_id: str, assignment_id: str,
    page: Sequence[tuple[int, str, Mapping[str, PlainData]]],
) -> tuple[dict[str, Any], int]:
    events: list[dict[str, Any]] = []
    request = {"session_id": session_id, "assignment_id": assignment_id, "events": events}
    size = len(_canonical_json(request).encode())
    for sequence, event_id, payload in page[:_MAX_BATCH_EVENTS]:
        event = {"sequence": sequence, "event_id": event_id, "payload": thaw_plain_data(payload)}
        size += len(_canonical_json(event).encode()) + bool(events)
        if size > _MAX_BODY_BYTES:
            break
        events.append(event)
    if not events:
        raise QueueServiceError("remote event exceeds the request byte budget")
    return request, page[len(events) - 1][0]


def apply_event_batch(view: AgentSessionView, value: Mapping[str, object]) -> Mapping[str, PlainData]:
    _exact(value, {"session_id", "assignment_id", "events"})
    session_id, assignment_id = _string(value, "session_id"), _string(value, "assignment_id")
    events = value["events"]
    if not isinstance(events, list) or not 1 <= len(events) <= _MAX_BATCH_EVENTS:
        raise QueueServiceError("remote event batch count is invalid")
    ordered = []
    for event in events:
        if not isinstance(event, Mapping):
            raise QueueServiceError("remote event is invalid")
        _exact(event, {"sequence", "event_id", "payload"})
        sequence, event_id = _integer(event, "sequence"), _string(event, "event_id")
        if sequence < 1 or (ordered and sequence != ordered[-1][0] + 1):
            raise QueueConflictError("remote event batch has a sequence gap")
        payload = event["payload"]
        if not isinstance(payload, Mapping):
            raise QueueServiceError("remote event payload is invalid")
        ordered.append((sequence, event_id, payload))
    for sequence, event_id, payload in ordered:
        # The single-event owner authorizes each append and verifies replayed
        # identity and content, including after interruption mid-batch.
        result = view.report_event(session_id, assignment_id, sequence=sequence, event_id=event_id, payload=payload)
        if result["acknowledged_sequence"] != sequence:
            raise QueueConflictError("remote event batch has an acknowledgement gap")
    return {
        "assignment_id": assignment_id, "acknowledged_sequence": ordered[-1][0],
        "request_digest": _canonical_digest(cast(Mapping[str, PlainData], value)),
    }
