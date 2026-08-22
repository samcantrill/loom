"""Explicit, instance-local active and retained component bindings."""

from __future__ import annotations
from collections.abc import Mapping
from types import MappingProxyType
from .values import SchedulingComponentDescriptor, SchedulingError


class ComponentRegistry:
    def __init__(self) -> None:
        self._active: dict[str, object] = {}
        self._retained: dict[tuple[str, int, str, str, str], object] = {}
        self._frozen = False

    @property
    def frozen(self) -> bool:
        return self._frozen

    def register(self, component: object, *, active: bool = True) -> None:
        if self._frozen:
            raise SchedulingError("component registry is frozen")
        descriptor = getattr(component, "descriptor", None)
        if not isinstance(descriptor, SchedulingComponentDescriptor):
            raise SchedulingError("component must have a SchedulingComponentDescriptor")
        if descriptor.key in self._retained:
            raise SchedulingError("duplicate component descriptor")
        if active and descriptor.kind in self._active:
            raise SchedulingError("duplicate active component kind")
        self._retained[descriptor.key] = component
        if active:
            self._active[descriptor.kind] = component

    def freeze(self) -> None:
        self._frozen = True

    def active(self, kind: str) -> object:
        try:
            return self._active[kind]
        except KeyError as exc:
            raise SchedulingError(f"unknown active component {kind!r}") from exc

    def retained(self, descriptor: SchedulingComponentDescriptor) -> object:
        try:
            return self._retained[descriptor.key]
        except KeyError as exc:
            raise SchedulingError("required retained component is unavailable") from exc

    @property
    def active_bindings(self) -> Mapping[str, object]:
        return MappingProxyType(dict(self._active))
