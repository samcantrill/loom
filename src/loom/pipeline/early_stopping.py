"""Cooperative early-stop signal shared by pipeline execution surfaces."""

from __future__ import annotations

from collections.abc import Mapping

from loom.pipeline.stores import LifecycleReason
from loom.serialization import PlainData, PlainDataError, ensure_plain_data

EARLY_STOP_REASON_CODE = "early_stop"


class EarlyStopSignal(Exception):
    """Signal raised by trusted stage code to request controlled cancellation."""

    def __init__(
        self,
        message: str,
        *,
        detail: Mapping[str, PlainData] | None = None,
    ) -> None:
        if not isinstance(message, str) or not message:
            raise ValueError("early-stop message must be a non-empty string")
        normalized_detail = _plain_detail(detail)
        super().__init__(message)
        self.message = message
        self.detail = normalized_detail

    def to_lifecycle_reason(self) -> LifecycleReason:
        """Return the structured lifecycle reason persisted for this signal."""

        return LifecycleReason(
            code=EARLY_STOP_REASON_CODE,
            message=self.message,
            detail=self.detail,
        )


def stop_early(
    message: str,
    *,
    detail: Mapping[str, PlainData] | None = None,
) -> None:
    """Raise a typed early-stop signal with plain-data detail."""

    raise EarlyStopSignal(message, detail=detail)


def lifecycle_reason_from_early_stop(signal: EarlyStopSignal) -> LifecycleReason:
    """Return the lifecycle reason for an early-stop signal."""

    if not isinstance(signal, EarlyStopSignal):
        raise TypeError("signal must be EarlyStopSignal")
    return signal.to_lifecycle_reason()


def _plain_detail(
    detail: Mapping[str, PlainData] | None,
) -> dict[str, PlainData]:
    if detail is None:
        return {}
    if not isinstance(detail, Mapping):
        raise ValueError("early-stop detail must be a mapping")
    try:
        normalized = ensure_plain_data(dict(detail), path="detail")
    except PlainDataError as exc:
        raise ValueError(f"early-stop detail must contain plain data: {exc}") from exc
    if not isinstance(normalized, dict):
        raise ValueError("early-stop detail must be a mapping")
    return normalized


__all__ = [
    "EARLY_STOP_REASON_CODE",
    "EarlyStopSignal",
    "lifecycle_reason_from_early_stop",
    "stop_early",
]
