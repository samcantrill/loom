"""Shared executor helpers for reliability policy metadata."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from loom.pipeline.reliability import (
    ReliabilityPolicy,
    TimeoutOutcome,
    TimeoutPolicy,
    TimeoutSupportLevel,
)
from loom.serialization import PlainData, ensure_plain_data


TIMEOUT_METADATA_KEY = "reliability_timeout"


def timeout_policy_from_request(request: object) -> TimeoutPolicy | None:
    """Return the resolved enabled timeout policy for an execution request."""

    runtime = getattr(request, "resolved_runtime", None)
    policy = getattr(runtime, "reliability", None)
    if not isinstance(policy, ReliabilityPolicy):
        return None
    timeout = policy.timeout
    if not isinstance(timeout, TimeoutPolicy) or not timeout.enabled:
        return None
    return timeout


def timeout_metadata(
    *,
    policy: TimeoutPolicy,
    support_level: TimeoutSupportLevel,
    outcome: TimeoutOutcome,
    timed_out: bool,
    reason_code: str | None = None,
    message: str | None = None,
    details: Mapping[str, PlainData] | None = None,
) -> dict[str, PlainData]:
    """Build plain executor metadata consumed by execution reliability writers."""

    payload: dict[str, Any] = {
        "enabled": True,
        "timeout_domain": "reliability",
        "duration_seconds": policy.duration_seconds,
        "support_level": support_level.value,
        "outcome": outcome.value,
        "timed_out": timed_out,
        "reason_code": reason_code or f"reliability.timeout.{outcome.value}",
    }
    if message is not None:
        payload["message"] = message
    if details:
        payload["details"] = dict(details)
    normalized = ensure_plain_data(payload, path=TIMEOUT_METADATA_KEY)
    if not isinstance(normalized, dict):
        raise TypeError("timeout metadata must be a plain mapping")
    return cast(dict[str, PlainData], normalized)


def metadata_with_timeout(
    metadata: Mapping[str, PlainData],
    timeout: Mapping[str, PlainData] | None,
) -> dict[str, PlainData]:
    """Attach timeout metadata to an executor metadata mapping when present."""

    updated = dict(metadata)
    if timeout is not None:
        updated[TIMEOUT_METADATA_KEY] = dict(timeout)
    return updated


__all__ = [
    "TIMEOUT_METADATA_KEY",
    "metadata_with_timeout",
    "timeout_metadata",
    "timeout_policy_from_request",
]
