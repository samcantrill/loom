"""Event sink plugin adapter."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from typing import cast

from loom.pipeline.event_sinks import EventSink, EventSinkRegistration, EventSinkRegistry

from .entrypoints import (
    LOOM_EVENT_SINKS_GROUP,
    PluginLoadResult,
    PluginRecord,
    load_entry_points,
)


def load_event_sink_entry_points(
    records: Iterable[PluginRecord],
    registry: EventSinkRegistry,
    *,
    selected: Iterable[PluginRecord] | None = None,
    strict: bool = True,
) -> PluginLoadResult:
    """Load selected event sink entry points into a caller-supplied registry."""

    def register_sink(record: PluginRecord, value: object) -> None:
        registration = _registration_from_plugin_value(value)
        registry.register(
            record.name,
            registration.sink,
            subscription=registration.subscription,
        )

    return load_entry_points(
        records=_filter_records(records, LOOM_EVENT_SINKS_GROUP),
        selected=_filter_records(selected, LOOM_EVENT_SINKS_GROUP)
        if selected is not None
        else None,
        strict=strict,
        register=register_sink,
    )


def _registration_from_plugin_value(value: object) -> EventSinkRegistration:
    """Normalize plugin values to an event sink registration."""

    if isinstance(value, EventSinkRegistration):
        return value
    if isinstance(value, type):
        return EventSinkRegistration(sink=_sink_from_class(value))
    if callable(value):
        callable_value = cast(Callable[..., object], value)
        if _callable_accepts_event_sink_args(callable_value):
            return EventSinkRegistration(sink=cast(EventSink, value))
        candidate = _sink_from_factory(cast(Callable[[], object], callable_value))
        if isinstance(candidate, EventSinkRegistration):
            return candidate
        return EventSinkRegistration(sink=candidate)
    raise TypeError(
        "event sink entry point value must be a callable sink, "
        "no-arg sink class, or no-arg factory"
    )


def _sink_from_class(sink_type: type[object]) -> EventSink:
    try:
        candidate = sink_type()
    except Exception as exc:
        raise TypeError(f"event sink class {sink_type!r} could not be instantiated") from exc
    return _as_sink(candidate)


def _sink_from_factory(factory: Callable[[], object]) -> EventSink | EventSinkRegistration:
    try:
        candidate = factory()
    except Exception as exc:
        raise TypeError(f"event sink factory {factory!r} raised: {exc}") from exc
    if isinstance(candidate, EventSinkRegistration):
        return candidate
    return _as_sink(candidate)


def _as_sink(candidate: object) -> EventSink:
    if callable(candidate) and _callable_accepts_event_sink_args(
        cast(Callable[..., object], candidate)
    ):
        return cast(EventSink, candidate)
    raise TypeError(f"event sink plugin value {candidate!r} is not a callable event sink")


def _callable_accepts_event_sink_args(value: Callable[..., object]) -> bool:
    try:
        signature = inspect.signature(value)
    except (TypeError, ValueError):
        return True
    try:
        signature.bind(object(), object())
    except TypeError:
        return False
    return True


def _filter_records(
    records: Iterable[PluginRecord] | None,
    group: str,
) -> tuple[PluginRecord, ...]:
    if records is None:
        return ()
    return tuple(record for record in records if record.group == group)


__all__ = [
    "load_event_sink_entry_points",
]
