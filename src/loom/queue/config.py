"""Queue service configuration normalization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import re
from pathlib import Path
from typing import cast

from loom.serialization import (
    PlainData,
    ensure_plain_data,
    freeze_plain_data,
    thaw_plain_data,
)
from loom.serialization.errors import PlainDataError

from .errors import QueueConfigError
from .assignments import EnvironmentListBinding, StaticSlot
from .models import (
    QUEUE_RECORD_SCHEMA_VERSION,
    QueueDefinition,
    QueuePool,
    QueuePoolMode,
    validate_one_queue_per_pool,
    validate_queue_id,
)

QUEUE_CONFIG_SCHEMA_VERSION = 2
_CONFIG_DEPENDENCY_HINT = (
    "Install `loom` with its `weave` dependency before loading queue YAML configs."
)


@dataclass(frozen=True, slots=True)
class QueueControllerSpec:
    """Normalized controller defaults for a queue service."""

    owner_id: str = "controller-1"
    default_pool_name: str | None = None
    max_active_items: int = 1
    max_dispatches_per_cycle: int | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "owner_id", validate_queue_id(self.owner_id, "owner_id")
        )
        if self.default_pool_name is not None:
            object.__setattr__(
                self,
                "default_pool_name",
                validate_queue_id(self.default_pool_name, "default_pool_name"),
            )
        for field_name, value in (("max_active_items", self.max_active_items),):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise QueueConfigError(
                    f"controller.{field_name} must be a positive integer"
                )
        if self.max_dispatches_per_cycle is not None and (
            isinstance(self.max_dispatches_per_cycle, bool)
            or not isinstance(self.max_dispatches_per_cycle, int)
            or self.max_dispatches_per_cycle <= 0
        ):
            raise QueueConfigError(
                "controller.max_dispatches_per_cycle must be a positive integer or null"
            )
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "owner_id": self.owner_id,
            "default_pool_name": self.default_pool_name,
            "max_active_items": self.max_active_items,
            "max_dispatches_per_cycle": self.max_dispatches_per_cycle,
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
        }


@dataclass(frozen=True, slots=True)
class LocalStaticAssignmentSpec:
    """Normalized v2 static-slot configuration for one pool resource."""

    resource_name: str
    slots: tuple[StaticSlot, ...]
    binding: EnvironmentListBinding

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "provider": "static-slots",
            "slots": [
                {
                    "id": slot.slot_id,
                    "coordination_key": slot.coordination_key,
                    "value": slot.value,
                    **({"label": slot.label} if slot.label is not None else {}),
                }
                for slot in self.slots
            ],
            "binding": {
                "type": "environment-list",
                "name": self.binding.name,
                "separator": self.binding.separator,
            },
        }


@dataclass(frozen=True, slots=True)
class QueueServiceSpec:
    """Normalized trusted queue service configuration."""

    pools: tuple[QueuePool, ...]
    queues: tuple[QueueDefinition, ...]
    db_path: str | None = None
    controller: QueueControllerSpec = field(default_factory=QueueControllerSpec)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    local_assignments: Mapping[str, Mapping[str, LocalStaticAssignmentSpec]] = field(
        default_factory=dict
    )
    schema_version: int = QUEUE_CONFIG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version not in {1, QUEUE_CONFIG_SCHEMA_VERSION}:
            raise QueueConfigError(
                f"unsupported queue config schema_version '{self.schema_version}', "
                f"expected 1 or {QUEUE_CONFIG_SCHEMA_VERSION}"
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
        if self.schema_version == 1 and (
            self.controller.max_active_items != 1
            or self.controller.max_dispatches_per_cycle is not None
        ):
            raise QueueConfigError(
                "controller cycle limits require queue config schema_version 2"
            )
        if self.schema_version == 1 and self.local_assignments:
            raise QueueConfigError(
                "local assignments require queue config schema_version 2"
            )
        if self.controller.default_pool_name is not None and not self.has_pool(
            self.controller.default_pool_name
        ):
            raise QueueConfigError(
                f"unknown controller default_pool_name: {self.controller.default_pool_name}"
            )
        object.__setattr__(self, "pools", pools)
        object.__setattr__(self, "queues", queues)
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))
        assignments: dict[str, Mapping[str, LocalStaticAssignmentSpec]] = {}
        logical_resource_names = {
            resource_name for pool in pools for resource_name in pool.resources
        }
        slot_ids: set[str] = set()
        slot_keys: set[str] = set()
        for pool_name, configured in self.local_assignments.items():
            if not self.has_pool(pool_name):
                raise QueueConfigError(
                    f"assignments reference unknown pool: {pool_name}"
                )
            pool = next(pool for pool in pools if pool.pool_name == pool_name)
            if pool.mode is not QueuePoolMode.MANAGED:
                raise QueueConfigError("local assignments require a managed queue pool")
            binding_names: set[str] = set()
            normalized: dict[str, LocalStaticAssignmentSpec] = {}
            for resource_name, assignment in configured.items():
                if not isinstance(assignment, LocalStaticAssignmentSpec):
                    raise QueueConfigError(
                        "local assignments must contain static assignment specs"
                    )
                if (
                    resource_name != assignment.resource_name
                    or resource_name not in pool.resources
                ):
                    raise QueueConfigError(
                        "assignment resources must be declared by their managed pool"
                    )
                if len(assignment.slots) != pool.resources[resource_name]:
                    raise QueueConfigError(
                        "static assignment inventory must equal the pool resource capacity"
                    )
                if assignment.binding.name in binding_names:
                    raise QueueConfigError(
                        "static assignment binding names must be unique per pool"
                    )
                binding_names.add(assignment.binding.name)
                for slot in assignment.slots:
                    if slot.slot_id in slot_ids or slot.coordination_key in slot_keys:
                        raise QueueConfigError(
                            "static slot ids and coordination keys must be unique"
                        )
                    if slot.coordination_key in logical_resource_names:
                        raise QueueConfigError(
                            "logical resources and static slot coordination keys must not collide"
                        )
                    slot_ids.add(slot.slot_id)
                    slot_keys.add(slot.coordination_key)
                normalized[resource_name] = assignment
            assignments[pool_name] = normalized
        object.__setattr__(self, "local_assignments", assignments)

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
        result: dict[str, PlainData] = {
            "schema_version": self.schema_version,
            "service": {"db_path": self.db_path},
            "pools": [pool.to_dict() for pool in self.pools],
            "queues": [queue.to_dict() for queue in self.queues],
            "controller": _controller_dict(
                self.controller, include_cycle_limits=self.schema_version >= 2
            ),
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
        }
        if self.schema_version >= 2 and self.local_assignments:
            result["adapters"] = {
                "local": {
                    "assignments": {
                        pool_name: {
                            resource_name: assignment.to_dict()
                            for resource_name, assignment in resources.items()
                        }
                        for pool_name, resources in self.local_assignments.items()
                    }
                }
            }
        return result


def normalize_queue_spec(config: object) -> QueueServiceSpec:
    """Normalize trusted queue config data into a service spec."""

    payload = _queue_section(config)
    # An omitted version is legacy authored config.  New cycle-limit writers
    # must opt into schema v2 explicitly.
    schema_version = payload.get("schema_version", 1)
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise QueueConfigError("schema_version must be an integer")
    service = _mapping(payload.get("service", {}), "service")
    db_path = payload.get("db_path", service.get("db_path"))
    if db_path is not None and not isinstance(db_path, str):
        raise QueueConfigError("db_path must be a string or null")
    pools = tuple(
        _pool_from_mapping(item, index)
        for index, item in enumerate(_sequence(payload.get("pools"), "pools"))
    )
    queues = tuple(
        _queue_from_mapping(item, index)
        for index, item in enumerate(_sequence(payload.get("queues"), "queues"))
    )
    controller = _controller_from_mapping(
        _mapping(payload.get("controller", {}), "controller"), schema_version
    )
    metadata = _mapping(payload.get("metadata", {}), "metadata")
    assignments = _local_assignments_from_mapping(
        payload.get("adapters", {}), schema_version
    )
    return QueueServiceSpec(
        pools=pools,
        queues=queues,
        db_path=db_path,
        controller=controller,
        metadata=cast(Mapping[str, PlainData], metadata),
        local_assignments=assignments,
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
        resources=cast(
            Mapping[str, int],
            _mapping(payload.get("resources", {}), f"pools[{index}].resources"),
        ),
        metadata=cast(
            Mapping[str, PlainData],
            _mapping(payload.get("metadata", {}), f"pools[{index}].metadata"),
        ),
        schema_version=QUEUE_RECORD_SCHEMA_VERSION,
    )


def _queue_from_mapping(value: object, index: int) -> QueueDefinition:
    payload = _mapping(value, f"queues[{index}]")
    queue_name = _required_name(payload, "queue_name", "name", f"queues[{index}]")
    pool_name = _required_name(payload, "pool_name", "pool", f"queues[{index}]")
    return QueueDefinition(
        queue_name=queue_name,
        pool_name=pool_name,
        metadata=cast(
            Mapping[str, PlainData],
            _mapping(payload.get("metadata", {}), f"queues[{index}].metadata"),
        ),
        schema_version=QUEUE_RECORD_SCHEMA_VERSION,
    )


def _controller_from_mapping(
    payload: Mapping[str, object], schema_version: int
) -> QueueControllerSpec:
    owner_id = payload.get("owner_id", "controller-1")
    if not isinstance(owner_id, str):
        raise QueueConfigError("controller.owner_id must be a string")
    default_pool_name = payload.get("default_pool_name")
    if default_pool_name is not None and not isinstance(default_pool_name, str):
        raise QueueConfigError("controller.default_pool_name must be a string or null")
    max_active_items = payload.get("max_active_items", 1)
    if isinstance(max_active_items, bool) or not isinstance(max_active_items, int):
        raise QueueConfigError("controller.max_active_items must be an integer")
    max_dispatches_per_cycle = payload.get("max_dispatches_per_cycle")
    if max_dispatches_per_cycle is not None and (
        isinstance(max_dispatches_per_cycle, bool)
        or not isinstance(max_dispatches_per_cycle, int)
    ):
        raise QueueConfigError(
            "controller.max_dispatches_per_cycle must be an integer or null"
        )
    if schema_version == 1 and (
        "max_active_items" in payload or "max_dispatches_per_cycle" in payload
    ):
        raise QueueConfigError(
            "controller cycle limits require queue config schema_version 2"
        )
    return QueueControllerSpec(
        owner_id=owner_id,
        default_pool_name=default_pool_name,
        max_active_items=max_active_items,
        max_dispatches_per_cycle=max_dispatches_per_cycle,
        metadata=cast(
            Mapping[str, PlainData],
            _mapping(payload.get("metadata", {}), "controller.metadata"),
        ),
    )


def _controller_dict(
    controller: QueueControllerSpec, *, include_cycle_limits: bool
) -> dict[str, PlainData]:
    result = controller.to_dict()
    if not include_cycle_limits:
        result.pop("max_active_items")
        result.pop("max_dispatches_per_cycle")
    return result


def _local_assignments_from_mapping(
    value: object, schema_version: int
) -> Mapping[str, Mapping[str, LocalStaticAssignmentSpec]]:
    adapters = _mapping(value, "adapters")
    if not adapters:
        return {}
    if schema_version < 2:
        raise QueueConfigError(
            "local assignments require queue config schema_version 2"
        )
    if set(adapters) != {"local"}:
        raise QueueConfigError("adapters supports only the local assignment record")
    local = _mapping(adapters["local"], "adapters.local")
    if set(local) != {"assignments"}:
        raise QueueConfigError("adapters.local supports only assignments")
    pools = _mapping(local["assignments"], "adapters.local.assignments")
    result: dict[str, Mapping[str, LocalStaticAssignmentSpec]] = {}
    for pool_name, resource_value in pools.items():
        validate_queue_id(pool_name, "assignment pool_name")
        resources = _mapping(resource_value, f"adapters.local.assignments.{pool_name}")
        parsed: dict[str, LocalStaticAssignmentSpec] = {}
        for resource_name, record_value in resources.items():
            if not isinstance(resource_name, str) or not resource_name:
                raise QueueConfigError(
                    "assignment resource names must be non-empty strings"
                )
            record = _mapping(
                record_value, f"adapters.local.assignments.{pool_name}.{resource_name}"
            )
            if set(record) != {"provider", "slots", "binding"}:
                raise QueueConfigError(
                    "static assignment records require provider, slots, and binding"
                )
            if record["provider"] != "static-slots":
                raise QueueConfigError("assignment provider must be static-slots")
            slot_values = _sequence(record["slots"], "assignment slots")
            slots: list[StaticSlot] = []
            seen_ids: set[str] = set()
            seen_keys: set[str] = set()
            for index, slot_value in enumerate(slot_values):
                slot = _mapping(slot_value, f"assignment slots[{index}]")
                if set(slot) - {"id", "coordination_key", "value", "label"} or not {
                    "id",
                    "coordination_key",
                    "value",
                }.issubset(slot):
                    raise QueueConfigError(
                        "static slots require id, coordination_key, value, and optional label"
                    )
                try:
                    parsed_slot = StaticSlot(
                        resource_name=resource_name,
                        slot_id=cast(str, slot["id"]),
                        coordination_key=cast(str, slot["coordination_key"]),
                        value=cast(str, slot["value"]),
                        label=cast(str | None, slot.get("label")),
                    )
                except Exception as exc:  # noqa: BLE001
                    raise QueueConfigError(str(exc)) from exc
                if (
                    parsed_slot.slot_id in seen_ids
                    or parsed_slot.coordination_key in seen_keys
                ):
                    raise QueueConfigError(
                        "static slot ids and coordination keys must be unique"
                    )
                seen_ids.add(parsed_slot.slot_id)
                seen_keys.add(parsed_slot.coordination_key)
                slots.append(parsed_slot)
            if not slots:
                raise QueueConfigError("static assignments require at least one slot")
            binding = _mapping(record["binding"], "assignment binding")
            if (
                set(binding) != {"type", "name", "separator"}
                or binding["type"] != "environment-list"
            ):
                raise QueueConfigError(
                    "assignment binding must be an environment-list record"
                )
            name = binding["name"]
            separator = binding["separator"]
            if (
                not isinstance(name, str)
                or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None
            ):
                raise QueueConfigError(
                    "assignment binding name must be environment-safe"
                )
            if not isinstance(separator, str) or not separator or "\0" in separator:
                raise QueueConfigError("assignment binding separator must be non-empty")
            if any("\0" in slot.value or separator in slot.value for slot in slots):
                raise QueueConfigError(
                    "assignment slot values must be environment-safe and not contain the binding separator"
                )
            parsed[resource_name] = LocalStaticAssignmentSpec(
                resource_name=resource_name,
                slots=tuple(slots),
                binding=EnvironmentListBinding(resource_name, name, separator),
            )
        result[pool_name] = parsed
    return result


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


def _plain_mapping(
    value: Mapping[str, PlainData], path: str
) -> Mapping[str, PlainData]:
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
