"""Resource-validator plugin adapter."""

from __future__ import annotations

from collections.abc import Iterable

from typing import cast

from loom.pipeline.resources import ResourceValidator, ResourceValidatorRegistry

from .entrypoints import LOOM_RESOURCE_VALIDATORS_GROUP, PluginLoadResult, PluginRecord, load_entry_points


def load_resource_validator_entry_points(
    records: Iterable[PluginRecord], registry: ResourceValidatorRegistry, *,
    selected: Iterable[PluginRecord] | None = None, strict: bool = True,
) -> tuple[ResourceValidatorRegistry, PluginLoadResult]:
    """Load direct validators, returning the immutable expanded registry."""
    current = registry

    def register(record: PluginRecord, value: object) -> None:
        nonlocal current
        if not callable(value):
            raise TypeError("resource validator entry point value must be callable")
        current = current.with_validator(record.name, cast(ResourceValidator, value))

    group_records = tuple(record for record in records if record.group == LOOM_RESOURCE_VALIDATORS_GROUP)
    selected_records = None if selected is None else tuple(
        record for record in selected if record.group == LOOM_RESOURCE_VALIDATORS_GROUP
    )
    result = load_entry_points(group_records, selected=selected_records, strict=strict, register=register)
    return current, result


__all__ = ["load_resource_validator_entry_points"]
