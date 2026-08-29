"""Discord webhook event sink and coordinator reporter example package."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .sink import DiscordWebhookSink, discord_event_sink

if TYPE_CHECKING:
    from .coordinator import DiscordCoordinatorReporter


def __getattr__(name: str) -> object:
    if name == "DiscordCoordinatorReporter":
        from .coordinator import DiscordCoordinatorReporter

        return DiscordCoordinatorReporter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["DiscordCoordinatorReporter", "DiscordWebhookSink", "discord_event_sink"]
