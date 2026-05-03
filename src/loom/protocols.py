"""Package-wide protocol definitions."""

from __future__ import annotations

from typing import Any, Protocol


class Validatable(Protocol):
    """Contract for objects that validate their own invariants."""

    def validate(self) -> None:
        """Validate object invariants."""


class Fingerprintable(Protocol):
    """Contract for objects that can report a stable fingerprint."""

    def fingerprint(self) -> str:
        """Return a stable fingerprint for the object."""


__all__ = ["Validatable", "Fingerprintable"]
