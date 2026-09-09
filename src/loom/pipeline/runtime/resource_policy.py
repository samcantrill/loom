"""Independent pipeline resource accounting and control selection."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from loom.pipeline.errors import RuntimeResourceError
from loom.serialization import PlainData

ALL_RESOURCES = "all"
_AXES = frozenset({"account_for", "enforce"})
_UNSET = object()


def _identifiers(value: object, *, path: str) -> str | tuple[str, ...]:
    if value == ALL_RESOURCES:
        return ALL_RESOURCES
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise RuntimeResourceError(f"{path} must be 'all' or a list")
    names = tuple(value)
    if any(not isinstance(name, str) or not name for name in names):
        raise RuntimeResourceError(f"{path} entries must be non-empty strings")
    if len(set(names)) != len(names):
        raise RuntimeResourceError(f"{path} entries must be unique")
    return tuple(sorted(names))


@dataclass(frozen=True, slots=True, init=False)
class ResourcePolicy:
    """Concrete two-axis selector; construction is deliberately keyword-only."""

    account_for: str | tuple[str, ...] | None
    enforce: str | tuple[str, ...] | None

    def __init__(
        self,
        *,
        account_for: str | Iterable[str] | object = _UNSET,
        enforce: str | Iterable[str] | object = _UNSET,
    ) -> None:
        # A new invocation has concrete defaults; a partial authored value keeps
        # its omitted sibling axis for profile/stage composition.
        if account_for is _UNSET and enforce is _UNSET:
            account_for, enforce = ALL_RESOURCES, ()
        object.__setattr__(
            self,
            "account_for", None if account_for is _UNSET else _identifiers(account_for, path="ResourcePolicy.account_for"),
        )
        object.__setattr__(
            self,
            "enforce", None if enforce is _UNSET else _identifiers(enforce, path="ResourcePolicy.enforce"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        result: dict[str, PlainData] = {}
        for axis in _AXES:
            value = getattr(self, axis)
            if value is not None:
                result[axis] = value if isinstance(value, str) else list(value)
        return result

    @classmethod
    def from_dict(cls, value: object) -> "ResourcePolicy":
        mapping = sparse_resource_policy(value, path="ResourcePolicy")
        instance = cls.__new__(cls)
        for axis in _AXES:
            raw = mapping.get(axis)
            object.__setattr__(
                instance,
                axis,
                None if raw is None else _identifiers(raw, path=f"ResourcePolicy.{axis}"),
            )
        return instance

    def resolved(self, inherited: "ResourcePolicy | None" = None) -> "ResourcePolicy":
        """Resolve omitted axes at the composition boundary only."""

        base = ResourcePolicy(account_for=ALL_RESOURCES, enforce=()) if inherited is None else inherited
        if base.account_for is None or base.enforce is None:
            base = base.resolved()
        return ResourcePolicy(
            account_for=base.account_for if self.account_for is None else self.account_for,
            enforce=base.enforce if self.enforce is None else self.enforce,
        )

    def select(
        self, present: Mapping[str, object] | Iterable[str]
    ) -> Mapping[str, tuple[str, ...]]:
        """Project only present, nonzero normalized resource kinds."""

        if isinstance(present, Mapping):
            kinds = tuple(
                sorted(
                    name
                    for name, entry in present.items()
                    if (
                        entry.get("amount")
                        if isinstance(entry, Mapping)
                        else getattr(entry, "amount", entry)
                    )
                    != 0
                )
            )
        else:
            kinds = tuple(sorted(set(present)))
        resolved = self.resolved()
        accounted = (
            kinds
            if resolved.account_for == ALL_RESOURCES
            else tuple(name for name in kinds if name in cast(tuple[str, ...], resolved.account_for))
        )
        enforced = (
            kinds
            if resolved.enforce == ALL_RESOURCES
            else tuple(name for name in kinds if name in cast(tuple[str, ...], resolved.enforce))
        )
        return MappingProxyType({"account_for": accounted, "enforce": enforced})


def sparse_resource_policy(value: object, *, path: str) -> Mapping[str, object]:
    """Validate an override while retaining omitted-axis inheritance."""

    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise RuntimeResourceError(f"{path} must be a string-keyed mapping")
    unknown = set(value) - _AXES
    if unknown:
        raise RuntimeResourceError(f"{path} fields must be account_for and enforce")
    result: dict[str, object] = {}
    for axis, raw in value.items():
        if raw is None:
            raise RuntimeResourceError(f"{path}.{axis} cannot be null")
        normalized = _identifiers(raw, path=f"{path}.{axis}")
        result[axis] = normalized if isinstance(normalized, str) else list(normalized)
    return MappingProxyType(result)


def coerce_resource_policy(value: object, *, path: str) -> ResourcePolicy:
    if isinstance(value, ResourcePolicy):
        return value
    if value is None:
        raise RuntimeResourceError(f"{path} cannot be null")
    try:
        return ResourcePolicy.from_dict(value)
    except RuntimeResourceError as exc:
        raise RuntimeResourceError(f"{path}: {exc}") from exc


def validate_resource_selection(
    selection: object,
    full_entries: Mapping[str, object],
    effective_policy: ResourcePolicy,
    *,
    path: str,
) -> Mapping[str, tuple[str, ...]]:
    """Validate the durable post-demand projection without recomputing it."""

    if not isinstance(selection, Mapping) or set(selection) != _AXES:
        raise RuntimeResourceError(f"{path} must contain account_for and enforce")
    normalized: dict[str, tuple[str, ...]] = {}
    for axis, value in selection.items():
        if isinstance(value, str) or not isinstance(value, Sequence):
            raise RuntimeResourceError(f"{path}.{axis} must be a list")
        names = tuple(value)
        if any(not isinstance(name, str) or not name for name in names):
            raise RuntimeResourceError(f"{path}.{axis} entries must be non-empty strings")
        if tuple(sorted(names)) != names or len(set(names)) != len(names):
            raise RuntimeResourceError(f"{path}.{axis} entries must be sorted and unique")
        normalized[axis] = names
    expected = effective_policy.select(full_entries)
    if normalized != expected:
        raise RuntimeResourceError(f"{path} conflicts with resource policy and demand")
    return MappingProxyType(normalized)


__all__ = [
    "ALL_RESOURCES",
    "ResourcePolicy",
    "coerce_resource_policy",
    "sparse_resource_policy",
    "validate_resource_selection",
]
