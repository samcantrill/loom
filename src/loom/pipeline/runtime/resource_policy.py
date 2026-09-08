"""Independent pipeline resource accounting and control selection."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from loom.pipeline.errors import RuntimeResourceError
from loom.serialization import PlainData


ALL_RESOURCES = "all"


def _identifiers(value: object, *, path: str, allow_all: bool) -> str | tuple[str, ...]:
    if allow_all and value == ALL_RESOURCES:
        return ALL_RESOURCES
    if isinstance(value, str) or not isinstance(value, Iterable):
        choices = "'all' or a list" if allow_all else "a list"
        raise RuntimeResourceError(f"{path} must be {choices}")
    names = tuple(value)
    if any(not isinstance(name, str) or not name for name in names):
        raise RuntimeResourceError(f"{path} entries must be non-empty strings")
    if len(set(names)) != len(names):
        raise RuntimeResourceError(f"{path} entries must be unique")
    return tuple(sorted(names))


@dataclass(frozen=True, slots=True)
class ResourcePolicy:
    """Select pipeline demand for accounting and additional controls.

    ``account_for='all'`` accounts for every present normalized resource.  A
    list selects only those identifiers.  ``enforce`` is always an explicit
    list; it requests supported additional controls without creating a claim.
    """

    account_for: str | Iterable[str] = ALL_RESOURCES
    enforce: Iterable[str] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "account_for",
            _identifiers(
                self.account_for, path="ResourcePolicy.account_for", allow_all=True
            ),
        )
        object.__setattr__(
            self,
            "enforce",
            _identifiers(self.enforce, path="ResourcePolicy.enforce", allow_all=False),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "account_for": self.account_for
            if isinstance(self.account_for, str)
            else list(self.account_for),
            "enforce": list(self.enforce),
        }

    @classmethod
    def from_dict(cls, value: object) -> "ResourcePolicy":
        if not isinstance(value, Mapping) or any(
            not isinstance(key, str) for key in value
        ):
            raise RuntimeResourceError("ResourcePolicy must be a string-keyed mapping")
        if set(value) != {"account_for", "enforce"}:
            raise RuntimeResourceError(
                "ResourcePolicy fields must be account_for and enforce"
            )
        if value["account_for"] is None or value["enforce"] is None:
            raise RuntimeResourceError("ResourcePolicy axes cannot be null")
        return cls(account_for=value["account_for"], enforce=value["enforce"])

    def select(self, present: Iterable[str]) -> Mapping[str, tuple[str, ...]]:
        """Project present normalized kinds; absent selections remain absent."""

        kinds = tuple(sorted(set(present)))
        accounted = (
            kinds
            if self.account_for == ALL_RESOURCES
            else tuple(name for name in kinds if name in self.account_for)
        )
        enforced = tuple(name for name in kinds if name in self.enforce)
        return MappingProxyType({"account_for": accounted, "enforce": enforced})


def coerce_resource_policy(value: object, *, path: str) -> ResourcePolicy:
    if isinstance(value, ResourcePolicy):
        return value
    if value is None:
        raise RuntimeResourceError(f"{path} cannot be null")
    try:
        return ResourcePolicy.from_dict(value)
    except RuntimeResourceError as exc:
        raise RuntimeResourceError(f"{path}: {exc}") from exc


__all__ = ["ALL_RESOURCES", "ResourcePolicy", "coerce_resource_policy"]
