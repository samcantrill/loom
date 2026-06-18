"""Codec plugin adapters."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from loom.io.codecs import Codec, CodecRegistry

from .entrypoints import LOOM_CODECS_GROUP, PluginLoadResult, PluginRecord, load_entry_points


def load_codec_entry_points(
    records: Iterable[PluginRecord],
    registry: CodecRegistry,
    *,
    selected: Iterable[PluginRecord] | None = None,
    strict: bool = True,
) -> PluginLoadResult:
    """Load selected codec entry points into a caller-supplied registry."""

    return load_entry_points(
        records=_filter_records(records, LOOM_CODECS_GROUP),
        selected=_filter_records(selected, LOOM_CODECS_GROUP) if selected is not None else None,
        strict=strict,
        register=lambda _record, value: registry.register(_codec_from_plugin_value(value)),
    )


def _codec_from_plugin_value(value: object) -> Codec:
    """Normalize plugin values to a codec instance."""

    if isinstance(value, type):
        return _codec_from_class(value)
    if isinstance(value, Codec):
        return value
    if callable(value):
        return _codec_from_factory(value)
    raise TypeError("codec entry point value must be an instance, no-arg class, or no-arg factory")


def _codec_from_class(codec_type: type[object]) -> Codec:
    try:
        candidate = codec_type()
    except Exception as exc:
        raise TypeError(f"codec class {codec_type!r} could not be instantiated") from exc
    return _as_codec(candidate)


def _codec_from_factory(codec_factory: Callable[[], object]) -> Codec:
    try:
        candidate = codec_factory()
    except Exception as exc:
        raise TypeError(f"codec factory {codec_factory!r} raised: {exc}") from exc
    return _as_codec(candidate)


def _as_codec(candidate: object) -> Codec:
    if isinstance(candidate, Codec):
        return candidate
    raise TypeError(f"codec plugin value {candidate!r} is not a valid codec instance")


def _filter_records(
    records: Iterable[PluginRecord] | None,
    group: str,
) -> tuple[PluginRecord, ...]:
    if records is None:
        return ()
    return tuple(record for record in records if record.group == group)


__all__ = [
    "load_codec_entry_points",
]
