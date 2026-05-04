"""Trusted recipe implementations for the config composition example."""

from __future__ import annotations

from typing import Any

from loom.config import Recipe


class RetentionPolicy(Recipe):
    days: int
    tier: str = "standard"

    def expand(self) -> dict[str, Any]:
        return {
            "days": self.days,
            "tier": self.tier,
            "label": f"{self.tier}-{self.days}d",
            "delete_after": f"{self.days} days",
        }

