"""Environment request models for runtime options."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

from loom.serialization import PlainData

from loom.pipeline.errors import RuntimeResourceError

_ENVIRONMENT_FIELDS = frozenset({"inherit", "set_variables", "unset_variables"})


@dataclass(frozen=True, slots=True)
class RunEnvironmentRequest:
    """Run-level environment changes requested for a future isolated executor."""

    inherit: bool = True
    set_variables: Mapping[str, str] = field(default_factory=dict)
    unset_variables: Sequence[str] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "inherit", _bool_value(self.inherit, path="RunEnvironmentRequest.inherit"))
        object.__setattr__(
            self,
            "set_variables",
            _environment_mapping(self.set_variables, path="RunEnvironmentRequest.set_variables"),
        )
        object.__setattr__(
            self,
            "unset_variables",
            _environment_name_tuple(self.unset_variables, path="RunEnvironmentRequest.unset_variables"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "inherit": self.inherit,
            "set_variables": dict(self.set_variables),
            "unset_variables": list(self.unset_variables),
        }

    @classmethod
    def from_dict(cls, data: object) -> "RunEnvironmentRequest":
        mapping = _environment_request_mapping(data, path="RunEnvironmentRequest")
        return cls(
            inherit=_bool_value(mapping.get("inherit", True), path="RunEnvironmentRequest.inherit"),
            set_variables=_environment_mapping(
                mapping.get("set_variables", {}),
                path="RunEnvironmentRequest.set_variables",
            ),
            unset_variables=_environment_name_tuple(
                mapping.get("unset_variables", ()),
                path="RunEnvironmentRequest.unset_variables",
            ),
        )

    def to_safe_metadata(self) -> dict[str, PlainData]:
        return _safe_environment_metadata(
            inherit=self.inherit,
            set_count=len(self.set_variables),
            unset_count=len(self.unset_variables),
        )


@dataclass(frozen=True, slots=True)
class StageEnvironmentRequest:
    """Stage-level environment changes requested for a future isolated executor."""

    inherit: bool = True
    set_variables: Mapping[str, str] = field(default_factory=dict)
    unset_variables: Sequence[str] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "inherit",
            _bool_value(self.inherit, path="StageEnvironmentRequest.inherit"),
        )
        object.__setattr__(
            self,
            "set_variables",
            _environment_mapping(
                self.set_variables,
                path="StageEnvironmentRequest.set_variables",
            ),
        )
        object.__setattr__(
            self,
            "unset_variables",
            _environment_name_tuple(
                self.unset_variables,
                path="StageEnvironmentRequest.unset_variables",
            ),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "inherit": self.inherit,
            "set_variables": dict(self.set_variables),
            "unset_variables": list(self.unset_variables),
        }

    @classmethod
    def from_dict(cls, data: object) -> "StageEnvironmentRequest":
        mapping = _environment_request_mapping(data, path="StageEnvironmentRequest")
        return cls(
            inherit=_bool_value(mapping.get("inherit", True), path="StageEnvironmentRequest.inherit"),
            set_variables=_environment_mapping(
                mapping.get("set_variables", {}),
                path="StageEnvironmentRequest.set_variables",
            ),
            unset_variables=_environment_name_tuple(
                mapping.get("unset_variables", ()),
                path="StageEnvironmentRequest.unset_variables",
            ),
        )

    def to_safe_metadata(self) -> dict[str, PlainData]:
        return _safe_environment_metadata(
            inherit=self.inherit,
            set_count=len(self.set_variables),
            unset_count=len(self.unset_variables),
        )


def _environment_request_mapping(value: object, *, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RuntimeResourceError(f"{path} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise RuntimeResourceError(f"{path} must be a mapping with string keys")
    unknown = set(value) - _ENVIRONMENT_FIELDS
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise RuntimeResourceError(f"{path} contains unknown field(s): {fields}")
    return cast(Mapping[str, object], value)


def _environment_mapping(value: object, *, path: str) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise RuntimeResourceError(f"{path} must be a mapping")
    normalized: dict[str, str] = {}
    for key, item in value.items():
        name = _environment_name(key, path=f"{path} key")
        if not isinstance(item, str):
            raise RuntimeResourceError(f"{path}[{name!r}] must be a string")
        normalized[name] = item
    return MappingProxyType(dict(sorted(normalized.items())))


def _environment_name_tuple(value: object, *, path: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise RuntimeResourceError(f"{path} must be a sequence of environment names")
    names: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        name = _environment_name(item, path=f"{path}[{index}]")
        if name in seen:
            raise RuntimeResourceError(f"{path} contains duplicate environment name {name!r}")
        seen.add(name)
        names.append(name)
    return tuple(sorted(names))


def _environment_name(value: object, *, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeResourceError(f"{path} must be a non-empty string")
    if "\x00" in value:
        raise RuntimeResourceError(f"{path} cannot contain NUL characters")
    if "=" in value:
        raise RuntimeResourceError(f"{path} cannot contain '='")
    return value


def _bool_value(value: object, *, path: str) -> bool:
    if not isinstance(value, bool):
        raise RuntimeResourceError(f"{path} must be a bool")
    return value


def _safe_environment_metadata(
    *,
    inherit: bool,
    set_count: int,
    unset_count: int,
) -> dict[str, PlainData]:
    return {
        "inherit": inherit,
        "set_variable_count": set_count,
        "unset_variable_count": unset_count,
    }


__all__ = ["RunEnvironmentRequest", "StageEnvironmentRequest"]
