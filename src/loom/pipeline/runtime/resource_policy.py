"""Independent pipeline resource accounting and control selection."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from loom.pipeline.errors import RuntimeResourceError
from loom.serialization import PlainData

ALL_RESOURCES = "all"
_AXES = frozenset({"account_for", "enforce"})


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

    account_for: str | tuple[str, ...]
    enforce: str | tuple[str, ...]

    def __init__(
        self,
        *,
        account_for: str | Iterable[str] = ALL_RESOURCES,
        enforce: str | Iterable[str] = (),
    ) -> None:
        object.__setattr__(
            self,
            "account_for",
            _identifiers(account_for, path="ResourcePolicy.account_for"),
        )
        object.__setattr__(
            self,
            "enforce",
            _identifiers(enforce, path="ResourcePolicy.enforce"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "account_for": self.account_for
            if isinstance(self.account_for, str)
            else list(self.account_for),
            "enforce": self.enforce
            if isinstance(self.enforce, str)
            else list(self.enforce),
        }

    @classmethod
    def from_dict(cls, value: object) -> "ResourcePolicy":
        mapping = sparse_resource_policy(value, path="ResourcePolicy")
        return cls(
            account_for=mapping.get("account_for", ALL_RESOURCES),
            enforce=mapping.get("enforce", ()),
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
        accounted = (
            kinds
            if self.account_for == ALL_RESOURCES
            else tuple(name for name in kinds if name in self.account_for)
        )
        enforced = (
            kinds
            if self.enforce == ALL_RESOURCES
            else tuple(name for name in kinds if name in self.enforce)
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


__all__ = [
    "ALL_RESOURCES",
    "ResourcePolicy",
    "coerce_resource_policy",
    "sparse_resource_policy",
]
