"""Artifact-store backend plugin adapter."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from loom.pipeline.stores.artifact_backends import (
    ArtifactStoreBackendDescriptor,
    ArtifactStoreBackendFactory,
    ArtifactStoreBackendRegistry,
)

from .entrypoints import (
    LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
    PluginLoadResult,
    PluginRecord,
    load_entry_points,
)


def load_artifact_store_backend_entry_points(
    records: Iterable[PluginRecord],
    registry: ArtifactStoreBackendRegistry,
    *,
    selected: Iterable[PluginRecord] | None = None,
    strict: bool = True,
    replace: bool = False,
) -> PluginLoadResult:
    """Load selected artifact-store backend entry points into a supplied registry."""

    def register_backend(_record: PluginRecord, value: object) -> None:
        registry.register(
            _backend_factory_from_plugin_value(value),
            replace=replace,
        )

    return load_entry_points(
        records=_filter_records(records, LOOM_ARTIFACT_STORE_BACKENDS_GROUP),
        selected=_filter_records(selected, LOOM_ARTIFACT_STORE_BACKENDS_GROUP)
        if selected is not None
        else None,
        strict=strict,
        register=register_backend,
    )


def _backend_factory_from_plugin_value(
    value: object,
) -> ArtifactStoreBackendFactory | ArtifactStoreBackendDescriptor:
    """Normalize plugin values to descriptor or factory registration targets."""

    if isinstance(value, ArtifactStoreBackendDescriptor):
        return value
    if isinstance(value, type):
        return _backend_factory_from_callable(value)
    if isinstance(value, ArtifactStoreBackendFactory):
        return value
    if callable(value):
        return _backend_factory_from_callable(value)
    raise TypeError(
        "artifact-store backend entry point value must be a descriptor, "
        "factory, no-arg class, or no-arg factory"
    )


def _backend_factory_from_callable(
    factory: Callable[[], object],
) -> ArtifactStoreBackendFactory | ArtifactStoreBackendDescriptor:
    try:
        candidate = factory()
    except Exception as exc:
        raise TypeError(
            f"artifact-store backend factory {factory!r} raised: {exc}"
        ) from exc
    if isinstance(candidate, ArtifactStoreBackendDescriptor):
        return candidate
    if isinstance(candidate, ArtifactStoreBackendFactory):
        return candidate
    raise TypeError(
        f"artifact-store backend factory {factory!r} did not return a descriptor "
        "or factory"
    )


def _filter_records(
    records: Iterable[PluginRecord] | None,
    group: str,
) -> tuple[PluginRecord, ...]:
    if records is None:
        return ()
    return tuple(record for record in records if record.group == group)


__all__ = [
    "load_artifact_store_backend_entry_points",
]
