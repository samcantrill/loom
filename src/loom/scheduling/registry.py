"""Explicit instance-local active and retained scheduling component bindings."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from types import MappingProxyType
from typing import TypeVar, cast

from .values import (
    HardConstraintSpec,
    PreferenceSpec,
    SchedulingComponentDescriptor,
    SchedulingError,
)

_Component = TypeVar("_Component")


class ComponentRegistry:
    """One configuration-epoch registry for one scheduling protocol family.

    Exact registration replay is harmless. Active bindings serve fresh
    resolution; descriptor-keyed retained bindings reconstruct referenced work.
    """

    def __init__(self, *, epoch_id: str = "default") -> None:
        if not isinstance(epoch_id, str) or not epoch_id:
            raise SchedulingError("component registry epoch_id is required")
        self._epoch_id = epoch_id
        self._active: dict[str, object] = {}
        self._retained: dict[tuple[str, int, str, str, str], object] = {}
        self._frozen = False

    @property
    def epoch_id(self) -> str:
        return self._epoch_id

    @property
    def frozen(self) -> bool:
        return self._frozen

    def register(self, component: object, *, active: bool = True) -> None:
        if self._frozen:
            raise SchedulingError("component registry is frozen")
        descriptor = getattr(component, "descriptor", None)
        if not isinstance(descriptor, SchedulingComponentDescriptor):
            raise SchedulingError("component must expose SchedulingComponentDescriptor")
        retained = self._retained.get(descriptor.key)
        if retained is not None and retained is not component:
            raise SchedulingError("duplicate component descriptor")
        if active:
            current = self._active.get(descriptor.kind)
            if current is not None and current is not component:
                raise SchedulingError("duplicate active component kind")
        self._retained[descriptor.key] = component
        if active:
            self._active[descriptor.kind] = component

    def freeze(self) -> ComponentRegistry:
        if not self._active:
            raise SchedulingError("component registry has no active bindings")
        self._frozen = True
        return self

    def active(self, kind: str) -> object:
        self._require_frozen()
        try:
            return self._active[kind]
        except KeyError as exc:
            raise SchedulingError(f"unknown active component {kind!r}") from exc

    def retained(self, descriptor: SchedulingComponentDescriptor) -> object:
        self._require_frozen()
        try:
            component = self._retained[descriptor.key]
        except KeyError as exc:
            raise SchedulingError("required retained component is unavailable") from exc
        retained_descriptor = cast(
            SchedulingComponentDescriptor, getattr(component, "descriptor")
        )
        if (
            descriptor.supported_data_versions
            != retained_descriptor.supported_data_versions
        ):
            raise SchedulingError("retained component data versions changed")
        return component

    def require_retained(
        self, descriptors: Sequence[SchedulingComponentDescriptor]
    ) -> tuple[object, ...]:
        return tuple(self.retained(descriptor) for descriptor in descriptors)

    def resolve_hard_spec(self, spec: HardConstraintSpec) -> HardConstraintSpec:
        component = self.active(spec.evaluator)
        descriptor = cast(
            SchedulingComponentDescriptor, getattr(component, "descriptor")
        )
        return replace(spec, descriptor=descriptor)

    def resolve_preference_spec(self, spec: PreferenceSpec) -> PreferenceSpec:
        component = self.active(spec.scorer)
        descriptor = cast(
            SchedulingComponentDescriptor, getattr(component, "descriptor")
        )
        return replace(spec, descriptor=descriptor)

    @property
    def active_bindings(self) -> Mapping[str, object]:
        self._require_frozen()
        return MappingProxyType(dict(self._active))

    @property
    def retained_descriptors(self) -> tuple[SchedulingComponentDescriptor, ...]:
        self._require_frozen()
        return tuple(
            sorted(
                (
                    cast(SchedulingComponentDescriptor, getattr(value, "descriptor"))
                    for value in self._retained.values()
                ),
                key=lambda value: value.key,
            )
        )

    def _require_frozen(self) -> None:
        if not self._frozen:
            raise SchedulingError("component registry must be frozen before use")


__all__ = ["ComponentRegistry"]
