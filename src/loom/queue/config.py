"""Queue service configuration normalization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from loom.serialization import PlainData, ensure_plain_data, freeze_plain_data, thaw_plain_data
from loom.serialization.errors import PlainDataError

from .errors import QueueConfigError
from .models import (
    QUEUE_RECORD_SCHEMA_VERSION,
    QueueDefinition,
    QueuePool,
    QueuePoolMode,
    validate_one_queue_per_pool,
    validate_queue_id,
)

QUEUE_CONFIG_SCHEMA_VERSION = 1
_CONFIG_DEPENDENCY_HINT = "Install `loom` with its `weave` dependency before loading queue YAML configs."


@dataclass(frozen=True, slots=True)
class QueueControllerSpec:
    """Normalized controller defaults for a queue service."""

    owner_id: str = "controller-1"
    default_pool_name: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", validate_queue_id(self.owner_id, "owner_id"))
        if self.default_pool_name is not None:
            object.__setattr__(
                self,
                "default_pool_name",
                validate_queue_id(self.default_pool_name, "default_pool_name"),
            )
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "owner_id": self.owner_id,
            "default_pool_name": self.default_pool_name,
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
        }


@dataclass(frozen=True, slots=True)
class QueueServiceSpec:
    """Normalized trusted queue service configuration."""

    pools: tuple[QueuePool, ...]
    queues: tuple[QueueDefinition, ...]
    db_path: str | None = None
    controller: QueueControllerSpec = field(default_factory=QueueControllerSpec)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = QUEUE_CONFIG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != QUEUE_CONFIG_SCHEMA_VERSION:
            raise QueueConfigError(
                f"unsupported queue config schema_version '{self.schema_version}', "
                f"expected {QUEUE_CONFIG_SCHEMA_VERSION}"
            )
        pools = tuple(self.pools)
        queues = tuple(self.queues)
        if not pools:
            raise QueueConfigError("queue config requires at least one pool")
        if not queues:
            raise QueueConfigError("queue config requires at least one queue")
        for pool in pools:
            if not isinstance(pool, QueuePool):
                raise QueueConfigError("pools must contain QueuePool records")
        for queue in queues:
            if not isinstance(queue, QueueDefinition):
                raise QueueConfigError("queues must contain QueueDefinition records")
        try:
            validate_one_queue_per_pool(pools, queues)
        except Exception as exc:
            raise QueueConfigError(str(exc)) from exc
        if self.db_path is not None and not isinstance(self.db_path, str):
            raise QueueConfigError("db_path must be a string or None")
        if not isinstance(self.controller, QueueControllerSpec):
            raise QueueConfigError("controller must be a QueueControllerSpec")
        if self.controller.default_pool_name is not None and not self.has_pool(
            self.controller.default_pool_name
        ):
            raise QueueConfigError(
                f"unknown controller default_pool_name: {self.controller.default_pool_name}"
            )
        object.__setattr__(self, "pools", pools)
        object.__setattr__(self, "queues", queues)
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    @property
    def pool_names(self) -> tuple[str, ...]:
        return tuple(pool.pool_name for pool in self.pools)

    @property
    def queue_names(self) -> tuple[str, ...]:
        return tuple(queue.queue_name for queue in self.queues)

    def has_pool(self, pool_name: str) -> bool:
        return any(pool.pool_name == pool_name for pool in self.pools)

    def queue_for_name(self, queue_name: str) -> QueueDefinition:
        queue_name = validate_queue_id(queue_name, "queue_name")
        for queue in self.queues:
            if queue.queue_name == queue_name:
                return queue
        raise QueueConfigError(f"unknown queue: {queue_name}")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "service": {"db_path": self.db_path},
            "pools": [pool.to_dict() for pool in self.pools],
            "queues": [queue.to_dict() for queue in self.queues],
            "controller": self.controller.to_dict(),
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
        }


def normalize_queue_spec(config: object) -> QueueServiceSpec:
    """Normalize trusted queue config data into a service spec."""

    payload = _queue_section(config)
    schema_version = payload.get("schema_version", QUEUE_CONFIG_SCHEMA_VERSION)
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise QueueConfigError("schema_version must be an integer")
    service = _mapping(payload.get("service", {}), "service")
    db_path = payload.get("db_path", service.get("db_path"))
    if db_path is not None and not isinstance(db_path, str):
        raise QueueConfigError("db_path must be a string or null")
    pools = tuple(_pool_from_mapping(item, index) for index, item in enumerate(_sequence(payload.get("pools"), "pools")))
    queues = tuple(
        _queue_from_mapping(item, index) for index, item in enumerate(_sequence(payload.get("queues"), "queues"))
    )
    controller = _controller_from_mapping(
        _mapping(payload.get("controller", {}), "controller")
    )
    metadata = _mapping(payload.get("metadata", {}), "metadata")
    return QueueServiceSpec(
        pools=pools,
        queues=queues,
        db_path=db_path,
        controller=controller,
        metadata=cast(Mapping[str, PlainData], metadata),
        schema_version=schema_version,
    )


def load_queue_spec(path: str | Path) -> QueueServiceSpec:
    """Load a trusted YAML queue config from an explicit path."""

    try:
        from weave.load import load_config
    except ModuleNotFoundError as exc:
        if exc.name == "yaml":
            raise QueueConfigError(_CONFIG_DEPENDENCY_HINT) from exc
        raise

    try:
        mapping, _source = load_config(path, kind="base", order=0)
    except Exception as exc:  # noqa: BLE001
        if exc.__class__.__module__.startswith("weave."):
            raise QueueConfigError(str(exc)) from exc
        raise
    return normalize_queue_spec(mapping)


def compose_queue_spec(
    config_path: str | Path,
    overlays: Sequence[str | Path] = (),
    overrides: Sequence[str] = (),
    *,
    include_raw_source_snapshots: bool = False,
) -> QueueServiceSpec:
    """Compose a project config with `weave` and normalize its queue section."""

    try:
        from weave import compose_config
    except Exception as exc:  # noqa: BLE001
        if exc.__class__.__module__.startswith("weave."):
            raise QueueConfigError(str(exc)) from exc
        raise
    composed = compose_config(
        config_path,
        overlays=tuple(overlays),
        overrides=tuple(overrides),
        include_raw_source_snapshots=include_raw_source_snapshots,
    )
    return queue_spec_from_composed_config(composed)


def queue_spec_from_composed_config(composed_config: object) -> QueueServiceSpec:
    """Normalize a composed config object or plain mapping into a queue spec."""

    resolved = getattr(composed_config, "resolved", composed_config)
    return normalize_queue_spec(resolved)


def _queue_section(config: object) -> Mapping[str, object]:
    plain = ensure_plain_data(config, path="queue_config")
    if not isinstance(plain, Mapping):
        raise QueueConfigError("queue config must be a mapping")
    if "queue" in plain:
        queue = plain["queue"]
        if not isinstance(queue, Mapping):
            raise QueueConfigError("queue section must be a mapping")
        return cast(Mapping[str, object], queue)
    return cast(Mapping[str, object], plain)


def _pool_from_mapping(value: object, index: int) -> QueuePool:
    payload = _mapping(value, f"pools[{index}]")
    pool_name = _required_name(payload, "pool_name", "name", f"pools[{index}]")
    mode = payload.get("mode")
    if not isinstance(mode, str):
        raise QueueConfigError(f"pools[{index}].mode must be a string")
    return QueuePool(
        pool_name=pool_name,
        mode=QueuePoolMode(mode),
        resources=cast(Mapping[str, int], _mapping(payload.get("resources", {}), f"pools[{index}].resources")),
        metadata=cast(Mapping[str, PlainData], _mapping(payload.get("metadata", {}), f"pools[{index}].metadata")),
        schema_version=QUEUE_RECORD_SCHEMA_VERSION,
    )


def _queue_from_mapping(value: object, index: int) -> QueueDefinition:
    payload = _mapping(value, f"queues[{index}]")
    queue_name = _required_name(payload, "queue_name", "name", f"queues[{index}]")
    pool_name = _required_name(payload, "pool_name", "pool", f"queues[{index}]")
    return QueueDefinition(
        queue_name=queue_name,
        pool_name=pool_name,
        metadata=cast(Mapping[str, PlainData], _mapping(payload.get("metadata", {}), f"queues[{index}].metadata")),
        schema_version=QUEUE_RECORD_SCHEMA_VERSION,
    )


def _controller_from_mapping(payload: Mapping[str, object]) -> QueueControllerSpec:
    owner_id = payload.get("owner_id", "controller-1")
    if not isinstance(owner_id, str):
        raise QueueConfigError("controller.owner_id must be a string")
    default_pool_name = payload.get("default_pool_name")
    if default_pool_name is not None and not isinstance(default_pool_name, str):
        raise QueueConfigError("controller.default_pool_name must be a string or null")
    return QueueControllerSpec(
        owner_id=owner_id,
        default_pool_name=default_pool_name,
        metadata=cast(Mapping[str, PlainData], _mapping(payload.get("metadata", {}), "controller.metadata")),
    )


def _required_name(
    payload: Mapping[str, object],
    canonical_key: str,
    alias_key: str,
    path: str,
) -> str:
    value = payload.get(canonical_key, payload.get(alias_key))
    if not isinstance(value, str):
        raise QueueConfigError(f"{path}.{canonical_key} must be a string")
    return value


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise QueueConfigError(f"{path} must be a mapping")
    for key in value:
        if not isinstance(key, str):
            raise QueueConfigError(f"{path} keys must be strings")
    return cast(Mapping[str, object], value)


def _sequence(value: object, path: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise QueueConfigError(f"{path} must be a sequence")
    return value


def _plain_mapping(value: Mapping[str, PlainData], path: str) -> Mapping[str, PlainData]:
    try:
        frozen = freeze_plain_data(value, path=path)
    except PlainDataError as exc:
        raise QueueConfigError(str(exc)) from exc
    if not isinstance(frozen, Mapping):
        raise QueueConfigError(f"{path} must be a mapping")
    return cast(Mapping[str, PlainData], frozen)


__all__ = [
    "QUEUE_CONFIG_SCHEMA_VERSION",
    "QueueControllerSpec",
    "QueueServiceSpec",
    "compose_queue_spec",
    "load_queue_spec",
    "normalize_queue_spec",
    "queue_spec_from_composed_config",
]
