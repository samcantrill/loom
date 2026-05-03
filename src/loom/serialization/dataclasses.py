"""Dataclass conversion helpers."""

from __future__ import annotations

import dataclasses
from dataclasses import fields, is_dataclass
from typing import Any, Mapping, TypeVar

from loom.serialization.plain import to_plain_data
from .errors import PlainDataError

DataClassT = TypeVar("DataClassT")


def dataclass_to_dict(value: Any, *, path: str = "$") -> dict[str, Any]:
    """Convert a dataclass instance to plain data."""

    if not is_dataclass(value) or isinstance(value, type):
        raise PlainDataError(f"Expected dataclass instance at {path}")
    return {
        name: to_plain_data(getattr(value, name), path=f"{path}.{name}") for name in (field.name for field in fields(value))
    }


def dataclass_from_dict(target_type: type[DataClassT], data: Mapping[str, Any], *, path: str = "$") -> DataClassT:
    """Reconstruct a dataclass from plain data."""

    if not dataclasses.is_dataclass(target_type):
        raise PlainDataError(f"Expected dataclass type at {path}: {target_type!r}")
    if not isinstance(data, dict):
        raise PlainDataError(f"Expected mapping input at {path}")

    target_fields = fields(target_type)
    field_names = {field.name: field for field in target_fields}
    required = {name for name, field in field_names.items() if field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING}

    extra = set(data) - set(field_names)
    if extra:
        raise PlainDataError(f"Unknown field(s) at {path}: {', '.join(sorted(extra))}")

    missing = required - set(data)
    if missing:
        raise PlainDataError(f"Missing required field(s) at {path}: {', '.join(sorted(missing))}")

    prepared = {name: to_plain_data(value, path=f"{path}.{name}") for name, value in data.items()}
    return target_type(**prepared)
