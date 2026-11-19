"""Provider settlement outcomes consumed before candidate verification."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ContinuationPending:
    reason: str


@dataclass(frozen=True, slots=True)
class ContinuationConflict:
    reason: str
