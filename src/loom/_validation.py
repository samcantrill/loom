"""Small, domain-neutral primitive validation helpers."""

from __future__ import annotations

from loom.errors import ValidationError


def require_positive_int(
    value: object,
    field: str,
    *,
    error_type: type[Exception] = ValidationError,
) -> int:
    """Return a positive integer while consistently rejecting booleans."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise error_type(f"{field} must be a positive integer")
    return value


def require_schema_version(
    value: object,
    *,
    field: str = "schema_version",
    current: int | None = None,
    error_type: type[Exception] = ValidationError,
) -> int:
    """Validate a positive schema version and, when requested, its exact value."""

    version = require_positive_int(value, field, error_type=error_type)
    if current is not None and version != current:
        raise error_type(f"{field} must be {current}")
    return version


__all__ = ["require_positive_int", "require_schema_version"]
