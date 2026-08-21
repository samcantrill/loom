"""Deterministic GPU pool planning over the existing managed-local queue seam."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from itertools import combinations
from dataclasses import dataclass, field
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, runtime_checkable
from urllib.parse import quote

from loom.pipeline.stores import (
    ConcurrencyCounter,
    CoordinationFailureKind,
    CoordinationStoreError,
    LifecycleReason,
    ResourceLeaseRecord,
    WorkspaceCoordinationStore,
)
from loom.serialization import PlainData
from loom.timestamps import parse_timestamp, utc_timestamp

from ..assignments import (
    LaunchEnvironmentBindings,
    ResourceAssignment,
    ResourceAssignmentDecision,
    ResourceAssignmentDisposition,
    ResourceAssignmentRequest,
    ResourceAssignmentProvider,
)
from ..config import QueueControllerSpec, QueueServiceSpec
from ..errors import QueueServiceError
from ..managed_local import ManagedLocalQueueRuntime
from ..local import LocalProcessRunner
from ..models import QueueDefinition, QueuePool, QueuePoolMode, validate_queue_id
from ..repository import QueueRepository


@dataclass(frozen=True, slots=True)
class LocalGpuDevice:
    """One trusted local GPU identity and its process-local binding value."""

    device_id: str
    binding_value: str

    def __post_init__(self) -> None:
        for field_name in ("device_id", "binding_value"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value or "\0" in value:
                raise QueueServiceError(
                    f"local GPU {field_name} must be a non-empty safe string"
                )
        if "," in self.binding_value:
            raise QueueServiceError(
                "local GPU binding_value must not contain the CUDA list separator"
            )


@dataclass(frozen=True, slots=True)
class LocalGpuLink:
    """One undirected, provider-local ordering relationship between two GPUs."""

    left_id: str
    right_id: str
    rank: int
    kind: str

    def __post_init__(self) -> None:
        for field_name in ("left_id", "right_id", "kind"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value or "\0" in value:
                raise QueueServiceError(
                    f"local GPU link {field_name} must be a non-empty safe string"
                )
        if self.left_id == self.right_id:
            raise QueueServiceError("local GPU links must join distinct device IDs")
        if (
            isinstance(self.rank, bool)
            or not isinstance(self.rank, int)
            or self.rank < 0
        ):
            raise QueueServiceError(
                "local GPU link rank must be a non-negative integer"
            )
        if self.right_id < self.left_id:
            left_id, right_id = self.right_id, self.left_id
            object.__setattr__(self, "left_id", left_id)
            object.__setattr__(self, "right_id", right_id)


@dataclass(frozen=True, slots=True)
class LocalGpuInventory:
    """Immutable operator-supplied local GPU inventory."""

    devices: tuple[LocalGpuDevice, ...]
    links: tuple[LocalGpuLink, ...] = ()

    def __post_init__(self) -> None:
        devices = tuple(self.devices)
        if not devices or not all(
            isinstance(device, LocalGpuDevice) for device in devices
        ):
            raise QueueServiceError(
                "local GPU inventory requires LocalGpuDevice values"
            )
        if len({device.device_id for device in devices}) != len(devices):
            raise QueueServiceError("local GPU device IDs must be unique")
        if len({device.binding_value for device in devices}) != len(devices):
            raise QueueServiceError("local GPU binding values must be unique")
        links = tuple(self.links)
        if not all(isinstance(link, LocalGpuLink) for link in links):
            raise QueueServiceError(
                "local GPU inventory links must be LocalGpuLink values"
            )
        device_ids = {device.device_id for device in devices}
        if any(
            link.left_id not in device_ids or link.right_id not in device_ids
            for link in links
        ):
            raise QueueServiceError("local GPU links must name inventory device IDs")
        if len({(link.left_id, link.right_id) for link in links}) != len(links):
            raise QueueServiceError("local GPU link pairs must be unique")
        object.__setattr__(
            self, "devices", tuple(sorted(devices, key=lambda item: item.device_id))
        )
        object.__setattr__(
            self,
            "links",
            tuple(sorted(links, key=lambda item: (item.left_id, item.right_id))),
        )


@runtime_checkable
class LocalGpuInventoryProvider(Protocol):
    """Injectable, explicit inventory discovery boundary."""

    def get_inventory(self) -> LocalGpuInventory: ...


@dataclass(frozen=True, slots=True)
class LocalGpuPoolLayout:
    """One supported integer-capacity layout for a device set."""

    kind: str
    shares: int = 1
    gpus_per_slot: int = 1
    grouping: str | None = None
    groups: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in {"whole", "shares", "grouped"}:
            raise QueueServiceError(
                "local GPU layout kind must be whole, shares, or grouped"
            )
        if (
            isinstance(self.shares, bool)
            or not isinstance(self.shares, int)
            or self.shares <= 0
        ):
            raise QueueServiceError("local GPU shares must be a positive integer")
        if self.kind == "whole" and self.shares != 1:
            raise QueueServiceError("whole GPU layouts require exactly one share")
        if self.kind != "grouped":
            if self.gpus_per_slot != 1 or self.grouping is not None or self.groups:
                raise QueueServiceError(
                    "only grouped GPU layouts may define grouping details"
                )
            return
        if self.shares != 1:
            raise QueueServiceError("grouped GPU layouts require exactly one share")
        if (
            isinstance(self.gpus_per_slot, bool)
            or not isinstance(self.gpus_per_slot, int)
            or self.gpus_per_slot <= 0
        ):
            raise QueueServiceError(
                "grouped GPU gpus_per_slot must be a positive integer"
            )
        if self.grouping not in {"explicit", "ordered", "topology"}:
            raise QueueServiceError(
                "grouped GPU layouts require explicit, ordered, or topology grouping"
            )
        groups = tuple(tuple(group) for group in self.groups)
        object.__setattr__(self, "groups", groups)
        if self.grouping == "explicit":
            if not groups:
                raise QueueServiceError("explicit grouped GPU layouts require groups")
            if any(
                len(group) != self.gpus_per_slot
                or any(
                    not isinstance(device_id, str) or not device_id
                    for device_id in group
                )
                for group in groups
            ):
                raise QueueServiceError(
                    "explicit GPU groups must contain exact-size non-empty device IDs"
                )
            normalized_groups = tuple(sorted(tuple(sorted(group)) for group in groups))
            if len(
                {device_id for group in normalized_groups for device_id in group}
            ) != sum(len(group) for group in normalized_groups):
                raise QueueServiceError("explicit GPU groups must be disjoint")
            object.__setattr__(self, "groups", normalized_groups)
        elif groups:
            raise QueueServiceError(
                "only explicit grouped GPU layouts may provide groups"
            )

    @classmethod
    def whole_gpus(cls) -> "LocalGpuPoolLayout":
        return cls("whole")

    @classmethod
    def shares_per_gpu(cls, shares: int) -> "LocalGpuPoolLayout":
        return cls("shares", shares)

    @classmethod
    def grouped(
        cls,
        gpus_per_slot: int,
        *,
        grouping: str = "explicit",
        groups: Iterable[Iterable[str]] | None = None,
    ) -> "LocalGpuPoolLayout":
        return cls(
            "grouped",
            gpus_per_slot=gpus_per_slot,
            grouping=grouping,
            groups=tuple(tuple(group) for group in (groups or ())),
        )


def whole_gpus() -> LocalGpuPoolLayout:
    """Use one queue unit and one authority lease per physical GPU."""

    return LocalGpuPoolLayout.whole_gpus()


def shares_per_gpu(shares: int) -> LocalGpuPoolLayout:
    """Use one queue unit per logical share; this does not isolate hardware."""

    return LocalGpuPoolLayout.shares_per_gpu(shares)


def grouped(
    gpus_per_slot: int,
    *,
    grouping: str = "explicit",
    groups: Iterable[Iterable[str]] | None = None,
) -> LocalGpuPoolLayout:
    """Use one logical queue unit backed by a disjoint group of physical GPUs."""

    return LocalGpuPoolLayout.grouped(gpus_per_slot, grouping=grouping, groups=groups)


@dataclass(frozen=True, slots=True)
class _GpuPlacement:
    device_ids: tuple[str, ...]


def _placements_for_layout(
    inventory: LocalGpuInventory, layout: LocalGpuPoolLayout
) -> tuple[_GpuPlacement, ...]:
    if layout.kind != "grouped":
        return ()
    device_ids = tuple(device.device_id for device in inventory.devices)
    if layout.grouping == "explicit":
        groups = layout.groups
        unknown = sorted(
            {
                device_id
                for group in groups
                for device_id in group
                if device_id not in device_ids
            }
        )
        if unknown:
            raise QueueServiceError(
                "explicit GPU groups name unknown inventory devices: "
                + ", ".join(unknown)
            )
        return tuple(_GpuPlacement(group) for group in groups)
    if layout.grouping == "ordered":
        groups = tuple(
            device_ids[index : index + layout.gpus_per_slot]
            for index in range(0, len(device_ids), layout.gpus_per_slot)
        )
        return tuple(
            _GpuPlacement(group)
            for group in groups
            if len(group) == layout.gpus_per_slot
        )
    candidates: list[tuple[int, int, tuple[str, ...]]] = []
    links = {(link.left_id, link.right_id): link for link in inventory.links}
    for group in combinations(device_ids, layout.gpus_per_slot):
        pair_links = [links.get(tuple(sorted(pair))) for pair in combinations(group, 2)]
        if any(link is None for link in pair_links):
            continue
        ranks = [link.rank for link in pair_links if link is not None]
        candidates.append((max(ranks, default=0), sum(ranks), group))
    selected: list[_GpuPlacement] = []
    used: set[str] = set()
    for _worst_rank, _total_rank, group in sorted(candidates):
        if not used.intersection(group):
            selected.append(_GpuPlacement(group))
            used.update(group)
    return tuple(selected)


@dataclass(frozen=True, slots=True)
class LocalGpuPoolPlan:
    """Prepared, deterministic queue composition for one local GPU inventory."""

    inventory: LocalGpuInventory
    layout: LocalGpuPoolLayout
    pool_name: str
    queue_name: str
    resource_name: str
    queue_spec: QueueServiceSpec
    required_limits: Mapping[str, int]
    fingerprint: str
    _placements: tuple[_GpuPlacement, ...] = field(repr=False, compare=False)
    _unused_device_ids: tuple[str, ...] = field(repr=False, compare=False, default=())

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "required_limits", MappingProxyType(dict(self.required_limits))
        )

    @property
    def capacity(self) -> int:
        return self.queue_spec.pools[0].resources[self.resource_name]

    def assignment_provider(
        self, store: WorkspaceCoordinationStore, *, workspace_id: str
    ) -> ResourceAssignmentProvider:
        return _LocalGpuAssignmentProvider(self, store, workspace_id=workspace_id)

    def safe_summary(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "fingerprint": self.fingerprint,
                "layout": self.layout.kind,
                "capacity": self.capacity,
                "pool_name": self.pool_name,
                "queue_name": self.queue_name,
                "resource_name": self.resource_name,
            }
        )

    def operator_summary(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                **self.safe_summary(),
                "devices": [
                    {
                        "device_id": device.device_id,
                        "binding_value": device.binding_value,
                    }
                    for device in self.inventory.devices
                ],
                "groups": [placement.device_ids for placement in self._placements],
                "unused_device_ids": self._unused_device_ids,
            }
        )


def plan_local_gpu_pool(
    inventory: LocalGpuInventory | LocalGpuInventoryProvider,
    layout: LocalGpuPoolLayout,
    *,
    pool_name: str = "gpu",
    queue_name: str = "gpu",
    resource_name: str | None = None,
    db_path: str | None = None,
    owner_id: str = "controller-1",
    max_active_items: int | None = None,
) -> LocalGpuPoolPlan:
    """Prepare one schema-v2 managed queue pool without mutating authority state."""

    resolved = _resolve_inventory(inventory)
    if not isinstance(layout, LocalGpuPoolLayout):
        raise QueueServiceError("layout must be a LocalGpuPoolLayout")
    pool_name = validate_queue_id(pool_name, "pool_name")
    queue_name = validate_queue_id(queue_name, "queue_name")
    resource_name = validate_queue_id(
        resource_name
        or {
            "whole": "gpu",
            "shares": "gpu_share",
            "grouped": "gpu_group",
        }[layout.kind],
        "resource_name",
    )
    placements = _placements_for_layout(resolved, layout)
    if layout.kind == "grouped" and not placements:
        raise QueueServiceError("local GPU layout cannot produce a complete group")
    capacity = (
        len(placements)
        if layout.kind == "grouped"
        else len(resolved.devices) * layout.shares
    )
    if max_active_items is None:
        max_active_items = capacity
    if (
        isinstance(max_active_items, bool)
        or not isinstance(max_active_items, int)
        or not 0 < max_active_items <= capacity
    ):
        raise QueueServiceError(
            "max_active_items must be a positive integer no greater than GPU capacity"
        )
    keys = {
        device.device_id: _device_key(device.device_id) for device in resolved.devices
    }
    required_limits = {resource_name: capacity}
    required_limits.update({key: layout.shares for key in keys.values()})
    placements = (
        tuple(_GpuPlacement((device.device_id,)) for device in resolved.devices)
        if layout.kind == "whole"
        else tuple(
            _GpuPlacement((device.device_id,))
            for share_round in range(layout.shares)
            for device in resolved.devices
        )
        if layout.kind == "shares"
        else placements
    )
    fingerprint = _fingerprint(
        resolved,
        layout,
        pool_name=pool_name,
        queue_name=queue_name,
        resource_name=resource_name,
    )
    spec = QueueServiceSpec(
        pools=(
            QueuePool(
                pool_name=pool_name,
                mode=QueuePoolMode.MANAGED,
                resources={resource_name: capacity},
                metadata={
                    "gpu_plan": {"fingerprint": fingerprint, "layout": layout.kind}
                },
            ),
        ),
        queues=(QueueDefinition(queue_name=queue_name, pool_name=pool_name),),
        db_path=db_path,
        controller=QueueControllerSpec(
            owner_id=owner_id,
            default_pool_name=pool_name,
            max_active_items=max_active_items,
        ),
        schema_version=2,
    )
    return LocalGpuPoolPlan(
        inventory=resolved,
        layout=layout,
        pool_name=pool_name,
        queue_name=queue_name,
        resource_name=resource_name,
        queue_spec=spec,
        required_limits=required_limits,
        fingerprint=fingerprint,
        _placements=placements,
        _unused_device_ids=tuple(
            device.device_id
            for device in resolved.devices
            if device.device_id
            not in {
                member for placement in placements for member in placement.device_ids
            }
        ),
    )


def ensure_local_gpu_pool_limits(
    plan: LocalGpuPoolPlan,
    store: WorkspaceCoordinationStore,
    *,
    workspace_id: str,
) -> tuple[ConcurrencyCounter, ...]:
    """Explicitly provision the prepared plan's immutable authority limits."""

    if not isinstance(plan, LocalGpuPoolPlan):
        raise QueueServiceError("plan must be a LocalGpuPoolPlan")
    return store.ensure_resource_limits(workspace_id, plan.required_limits)


def build_managed_local_gpu_runtime(
    plan: LocalGpuPoolPlan,
    *,
    workspace_id: str,
    coordination_store: WorkspaceCoordinationStore,
    repository: QueueRepository | None = None,
    process_runner: LocalProcessRunner | None = None,
    current_drift_inputs: Mapping[str, PlainData] | None = None,
    lease_ttl_seconds: int = 60,
    wait_timeout_seconds: float = 0.0,
    log_directory: str | Path | None = None,
    clock: Callable[[], str] = utc_timestamp,
) -> ManagedLocalQueueRuntime:
    """Read-only validate a plan, then delegate process lifecycle to managed-local."""

    _require_plan_limits(plan, coordination_store, workspace_id=workspace_id)
    return ManagedLocalQueueRuntime.from_spec(
        plan.queue_spec,
        workspace_id=workspace_id,
        coordination_store=coordination_store,
        pool_name=plan.pool_name,
        repository=repository,
        process_runner=process_runner,
        current_drift_inputs=current_drift_inputs,
        lease_ttl_seconds=lease_ttl_seconds,
        wait_timeout_seconds=wait_timeout_seconds,
        assignment_provider=plan.assignment_provider(
            coordination_store, workspace_id=workspace_id
        ),
        log_directory=log_directory,
        clock=clock,
    )


class _LocalGpuAssignmentProvider:
    provider_name = "local-gpu"

    def __init__(
        self,
        plan: LocalGpuPoolPlan,
        store: WorkspaceCoordinationStore,
        *,
        workspace_id: str,
    ) -> None:
        self._plan = plan
        self._store = store
        self._workspace_id = workspace_id
        self._devices = {device.device_id: device for device in plan.inventory.devices}
        self._next_share_placement = 0

    def acquire(self, request: ResourceAssignmentRequest) -> ResourceAssignmentDecision:
        amount = request.resources.get(self._plan.resource_name)
        if len(request.resources) != 1 or amount is None:
            return _failed("resource_assignment.request_invalid")
        if self._plan.layout.kind == "grouped" and amount != 1:
            return _failed("resource_assignment.group_amount_invalid")
        if self._plan.layout.kind == "shares" and amount != 1:
            return _failed("resource_assignment.share_amount_invalid")
        if self._plan.layout.kind == "whole" and amount > len(self._devices):
            return _failed("resource_assignment.request_exceeds_inventory")
        if self._plan.layout.kind == "whole":
            return self._acquire_whole(
                request,
                amount,
                tuple(
                    item for item in self._plan._placements if len(item.device_ids) == 1
                ),
            )
        candidates = self._plan._placements
        for offset in range(len(candidates)):
            index = (self._next_share_placement + offset) % len(candidates)
            placement = candidates[index]
            decision = self._try_placement(request, placement)
            if decision is not None:
                self._next_share_placement = (index + 1) % len(candidates)
                return decision
        return ResourceAssignmentDecision(
            ResourceAssignmentDisposition.DEFERRED,
            reason_code="resource_assignment.capacity_unavailable",
        )

    def _acquire_whole(
        self,
        request: ResourceAssignmentRequest,
        amount: int,
        candidates: tuple[_GpuPlacement, ...],
    ) -> ResourceAssignmentDecision:
        selected: list[ResourceLeaseRecord] = []
        for placement in candidates:
            lease = self._acquire_device(request, placement.device_ids[0])
            if lease is None:
                continue
            selected.append(lease)
            if len(selected) == amount:
                return self._assignment(selected)
        self._release_partial(selected)
        return ResourceAssignmentDecision(
            ResourceAssignmentDisposition.DEFERRED,
            reason_code="resource_assignment.capacity_unavailable",
        )

    def _try_placement(
        self, request: ResourceAssignmentRequest, placement: _GpuPlacement
    ) -> ResourceAssignmentDecision | None:
        leases: list[ResourceLeaseRecord] = []
        for device_id in placement.device_ids:
            try:
                lease = self._store.acquire_resource_lease(
                    self._workspace_id,
                    _device_key(device_id),
                    owner_id=f"{request.owner_id}:{request.session_id}",
                    amount=1,
                    lease_ttl_seconds=request.lease_ttl_seconds,
                )
            except CoordinationStoreError as exc:
                self._release_partial(leases)
                if exc.kind is CoordinationFailureKind.CAPACITY:
                    return None
                return _failed(f"resource_assignment.{exc.kind.value}")
            except Exception:  # noqa: BLE001
                self._release_partial(leases)
                return _failed("resource_assignment.internal")
            leases.append(lease)
        return self._assignment(leases)

    def _acquire_device(
        self, request: ResourceAssignmentRequest, device_id: str
    ) -> ResourceLeaseRecord | None:
        try:
            return self._store.acquire_resource_lease(
                self._workspace_id,
                _device_key(device_id),
                owner_id=f"{request.owner_id}:{request.session_id}",
                amount=1,
                lease_ttl_seconds=request.lease_ttl_seconds,
            )
        except CoordinationStoreError as exc:
            if exc.kind is CoordinationFailureKind.CAPACITY:
                return None
            raise QueueServiceError(
                f"GPU assignment authority failure: {exc.kind.value}"
            ) from exc

    def _assignment(
        self, leases: list[ResourceLeaseRecord]
    ) -> ResourceAssignmentDecision:
        selected = [
            self._devices[_device_id_for_key(lease.resource_key, self._devices)]
            for lease in leases
        ]
        return ResourceAssignmentDecision(
            ResourceAssignmentDisposition.ASSIGNED,
            assignment=ResourceAssignment(
                provider_name=self.provider_name,
                live_token=tuple(lease.lease.lease_id for lease in leases),
                leases=tuple(leases),
                bindings=LaunchEnvironmentBindings(
                    {
                        "CUDA_VISIBLE_DEVICES": ",".join(
                            device.binding_value for device in selected
                        )
                    }
                ),
                safe_evidence={
                    "slots": [
                        {
                            "resource_name": self._plan.resource_name,
                            "slot_id": f"gpu-{self._plan.inventory.devices.index(device)}",
                            "lease_id": lease.lease.lease_id,
                            "expires_at": lease.lease.expires_at,
                        }
                        for device, lease in zip(selected, leases, strict=True)
                    ]
                },
                next_maintenance_at=_lease_maintenance_at(tuple(leases)),
            ),
        )

    def renew(self, assignment: ResourceAssignment) -> ResourceAssignment:
        renewed = tuple(
            self._store.renew_lease(
                lease.lease.lease_id,
                owner_id=lease.lease.owner_id,
                fencing_token=lease.lease.fencing_token,
                lease_ttl_seconds=_ttl_from_assignment(assignment),
            )
            for lease in assignment.leases
        )
        leases = tuple(
            ResourceLeaseRecord(old.workspace_id, old.resource_key, new, old.amount)
            for old, new in zip(assignment.leases, renewed, strict=True)
        )
        decision = self._assignment(list(leases))
        assert decision.assignment is not None
        return decision.assignment

    def release(
        self, assignment: ResourceAssignment, *, reason: LifecycleReason
    ) -> None:
        first_error: Exception | None = None
        first_unfinished_error: Exception | None = None
        for lease in reversed(assignment.leases):
            try:
                self._store.release_lease(
                    lease.lease.lease_id,
                    owner_id=lease.lease.owner_id,
                    fencing_token=lease.lease.fencing_token,
                    reason=reason,
                )
            except Exception as exc:  # noqa: BLE001
                if first_error is None:
                    first_error = exc
                if first_unfinished_error is None and (
                    not isinstance(exc, CoordinationStoreError)
                    or exc.kind is not CoordinationFailureKind.OWNERSHIP_LOST
                ):
                    first_unfinished_error = exc
        if first_unfinished_error is not None:
            raise first_unfinished_error
        if first_error is not None:
            raise first_error

    def _release_partial(self, leases: list[ResourceLeaseRecord]) -> None:
        for lease in reversed(leases):
            self._store.release_lease(
                lease.lease.lease_id,
                owner_id=lease.lease.owner_id,
                fencing_token=lease.lease.fencing_token,
                reason=LifecycleReason(code="gpu_assignment_partial_release"),
            )


def _resolve_inventory(
    inventory: LocalGpuInventory | LocalGpuInventoryProvider,
) -> LocalGpuInventory:
    if isinstance(inventory, LocalGpuInventory):
        return inventory
    if not isinstance(inventory, LocalGpuInventoryProvider):
        raise QueueServiceError("inventory must be LocalGpuInventory or provider")
    resolved = inventory.get_inventory()
    if not isinstance(resolved, LocalGpuInventory):
        raise QueueServiceError(
            "local GPU inventory provider returned an invalid inventory"
        )
    return resolved


def _device_key(device_id: str) -> str:
    return "loom.gpu.device." + quote(device_id, safe="-._")


def _device_id_for_key(key: str, devices: Mapping[str, LocalGpuDevice]) -> str:
    return next(device_id for device_id in devices if _device_key(device_id) == key)


def _fingerprint(
    inventory: LocalGpuInventory,
    layout: LocalGpuPoolLayout,
    *,
    pool_name: str,
    queue_name: str,
    resource_name: str,
) -> str:
    canonical = json.dumps(
        {
            "device_ids": [device.device_id for device in inventory.devices],
            "links": [
                {
                    "left_id": link.left_id,
                    "right_id": link.right_id,
                    "rank": link.rank,
                    "kind": link.kind,
                }
                for link in inventory.links
            ],
            "layout": {
                "kind": layout.kind,
                "shares": layout.shares,
                "gpus_per_slot": layout.gpus_per_slot,
                "grouping": layout.grouping,
                "groups": layout.groups,
            },
            "pool_name": pool_name,
            "queue_name": queue_name,
            "resource_name": resource_name,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _require_plan_limits(
    plan: LocalGpuPoolPlan, store: WorkspaceCoordinationStore, *, workspace_id: str
) -> None:
    failures = [
        key
        for key, expected in plan.required_limits.items()
        if (counter := store.read_resource_limit(workspace_id, key)) is None
        or counter.limit != expected
    ]
    if failures:
        raise QueueServiceError(
            "local GPU plan resource limits do not match authority: "
            + ", ".join(failures)
        )


def _failed(code: str) -> ResourceAssignmentDecision:
    return ResourceAssignmentDecision(
        ResourceAssignmentDisposition.FAILED, reason_code=code
    )


def _ttl_from_assignment(assignment: ResourceAssignment) -> int:
    if not assignment.leases:
        return 1
    lease = assignment.leases[0].lease
    return max(
        1,
        round(
            (
                parse_timestamp(lease.expires_at) - parse_timestamp(lease.renewed_at)
            ).total_seconds()
        ),
    )


def _lease_maintenance_at(leases: tuple[ResourceLeaseRecord, ...]) -> str | None:
    if not leases:
        return None
    ttl = _ttl_from_leases(leases)
    return utc_timestamp(
        min(parse_timestamp(lease.lease.renewed_at) for lease in leases)
        + timedelta(seconds=ttl * 0.5)
    )


def _ttl_from_leases(leases: tuple[ResourceLeaseRecord, ...]) -> int:
    lease = leases[0].lease
    return max(
        1,
        round(
            (
                parse_timestamp(lease.expires_at) - parse_timestamp(lease.renewed_at)
            ).total_seconds()
        ),
    )
