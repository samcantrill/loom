"""Bounded, best-effort Discord webhook projection for Loom events."""

from __future__ import annotations

import math
import os

import httpx

from loom.pipeline.event_sinks import (
    EventSinkContext,
    EventSinkRegistration,
    EventSinkSubscription,
)
from loom.pipeline.events import EventReference, PipelineEventRecord


WEBHOOK_URL_ENVIRONMENT_VARIABLE = "LOOM_DISCORD_WEBHOOK_URL"
DEFAULT_TIMEOUT_SECONDS = 5.0
MAX_CONTENT_LENGTH = 2_000
MAX_EVENT_TYPE_LENGTH = 200
MAX_RUN_URI_LENGTH = 1_300
MAX_TIMESTAMP_LENGTH = 100
MAX_STAGE_NAME_LENGTH = 200
TERMINAL_RUN_EVENT_TYPES = (
    "run.cancelled",
    "run.completed",
    "run.failed",
    "run.interrupted",
    "run.preparation_failed",
)


class DiscordWebhookError(RuntimeError):
    """A sanitized Discord webhook delivery failure."""


class DiscordWebhookSink:
    """Project a committed Loom event to one bounded Discord webhook message."""

    def __init__(
        self,
        webhook_url: str,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not webhook_url:
            raise ValueError("webhook_url must be non-empty")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a positive finite number")
        self._webhook_url = webhook_url
        self._timeout_seconds = timeout_seconds

    def __call__(
        self,
        event: PipelineEventRecord | EventReference,
        context: EventSinkContext,
    ) -> None:
        _ = context
        reference = (
            event.to_event_reference()
            if isinstance(event, PipelineEventRecord)
            else event
        )
        _send_webhook_content(
            self._webhook_url,
            _message_content(event, reference),
            timeout_seconds=self._timeout_seconds,
        )


def discord_event_sink() -> EventSinkRegistration:
    """Build the default terminal-run sink from its process-local secret."""

    webhook_url = os.environ.get(WEBHOOK_URL_ENVIRONMENT_VARIABLE)
    if not webhook_url:
        raise RuntimeError(f"{WEBHOOK_URL_ENVIRONMENT_VARIABLE} must be set")
    return EventSinkRegistration(
        sink=DiscordWebhookSink(webhook_url),
        subscription=EventSinkSubscription(event_types=TERMINAL_RUN_EVENT_TYPES),
    )


def _message_content(
    event: PipelineEventRecord | EventReference,
    reference: EventReference,
) -> str:
    lines = [
        f"Loom event: {_clip(reference.event_type, MAX_EVENT_TYPE_LENGTH)}",
        f"Run: {_clip(reference.run_uri, MAX_RUN_URI_LENGTH)}",
        f"Occurred: {_clip(reference.occurred_at, MAX_TIMESTAMP_LENGTH)}",
    ]
    if isinstance(event, PipelineEventRecord) and event.primary_resource.kind == "stage":
        stage_name = event.primary_resource.identifiers.get("stage_name")
        if isinstance(stage_name, str):
            lines.append(f"Stage: {_clip(stage_name, MAX_STAGE_NAME_LENGTH)}")
    return "\n".join(lines)[:MAX_CONTENT_LENGTH]


def _send_webhook_content(
    webhook_url: str,
    content: str,
    *,
    timeout_seconds: float,
) -> None:
    """Send one bounded message without exposing provider details on failure."""

    try:
        response = httpx.post(
            webhook_url,
            params={"wait": "true"},
            json={
                "content": content[:MAX_CONTENT_LENGTH],
                "allowed_mentions": {"parse": []},
            },
            timeout=timeout_seconds,
        )
    except httpx.InvalidURL:
        raise DiscordWebhookError("Discord webhook URL is invalid") from None
    except httpx.HTTPError:
        raise DiscordWebhookError("Discord webhook transport failed") from None
    if not 200 <= response.status_code < 300:
        raise DiscordWebhookError(
            f"Discord webhook rejected request with status {response.status_code}"
        )


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 1]}…"
