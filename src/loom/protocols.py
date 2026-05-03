"""Package-wide protocol definitions."""

from __future__ import annotations

from typing import Protocol


class Validatable(Protocol):
    """Contract for objects that validate their own invariants."""

    def validate(self) -> None: ...


class Fingerprintable(Protocol):
    """Contract for objects that can report a stable fingerprint."""

    def fingerprint(self) -> str: ...


__all__ = ["Validatable", "Fingerprintable"]
