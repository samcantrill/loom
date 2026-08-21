"""Executor plugin adapter."""

from __future__ import annotations

from collections.abc import Iterable

from loom.pipeline.executors import ExecutorRegistration, ExecutorRegistry

from .entrypoints import LOOM_EXECUTORS_GROUP, PluginLoadResult, PluginRecord, load_entry_points


def load_executor_entry_points(
    records: Iterable[PluginRecord], registry: ExecutorRegistry, *,
    selected: Iterable[PluginRecord] | None = None, strict: bool = True,
) -> PluginLoadResult:
    """Load selected executor registrations into a caller-owned registry."""
    return load_entry_points(
        _group_records(records), selected=_group_records(selected) if selected is not None else None,
        strict=strict, register=lambda record, value: _register(registry, record, value),
    )


def _group_records(records: Iterable[PluginRecord] | None) -> tuple[PluginRecord, ...]:
    return () if records is None else tuple(record for record in records if record.group == LOOM_EXECUTORS_GROUP)


def _register(registry: ExecutorRegistry, record: PluginRecord, value: object) -> None:
    registration = _registration_from_value(value)
    if registration.descriptor.name != record.name:
        raise TypeError("executor entry-point name must match registration descriptor name")
    registry.register(registration)


def _registration_from_value(value: object) -> ExecutorRegistration:
    if isinstance(value, ExecutorRegistration):
        return value
    if callable(value):
        candidate = value()
        if isinstance(candidate, ExecutorRegistration):
            return candidate
    raise TypeError("executor entry point value must be an ExecutorRegistration or no-arg factory")


__all__ = ["load_executor_entry_points"]
