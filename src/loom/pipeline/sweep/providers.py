"""Provider and proposal contracts for deterministic sweeps."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, cast, runtime_checkable

from loom.serialization import PlainData, PlainDataError, ensure_plain_data

from .errors import SweepProtocolError


def _required(mapping: Mapping[str, Any], field_name: str) -> object:
    if field_name not in mapping:
        raise SweepProtocolError(f"missing required field {field_name!r}")
    return mapping[field_name]


def _reject_unknown(mapping: Mapping[str, object], allowed: set[str], *, object_name: str) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise SweepProtocolError(
            f"{object_name} payload has unknown field(s): {fields}"
        )


def _non_empty_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise SweepProtocolError(f"{field_name} must be a non-empty string")
    return value


def _optional_non_empty_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SweepProtocolError(f"{field_name} must be a string when set")
    if not value:
        raise SweepProtocolError(f"{field_name} must be a non-empty string when set")
    return value


def _plain_mapping(value: object, field_name: str) -> dict[str, PlainData]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise SweepProtocolError(f"{field_name} must be a mapping")
    try:
        normalized = ensure_plain_data(value, path=field_name)
    except (PlainDataError, TypeError) as exc:
        raise SweepProtocolError(
            f"{field_name} must contain plain data"
        ) from exc
    if not isinstance(normalized, dict):
        raise SweepProtocolError(f"{field_name} must be a mapping")
    return dict(normalized)


def _non_negative_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SweepProtocolError(f"{field_name} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class SweepProviderIdentity:
    """Provider identity facts used for manifest and dispatch records."""

    provider_name: str
    provider_type: str
    version: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_name", _non_empty_text(self.provider_name, "provider_name"))
        object.__setattr__(self, "provider_type", _non_empty_text(self.provider_type, "provider_type"))
        object.__setattr__(self, "version", _optional_non_empty_text(self.version, "version"))
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "provider_type": self.provider_type,
            "version": self.version,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "SweepProviderIdentity":
        if not isinstance(data, Mapping):
            raise SweepProtocolError("SweepProviderIdentity payload must be a mapping")
        _reject_unknown(
            data,
            {"provider_name", "provider_type", "version", "metadata"},
            object_name="SweepProviderIdentity",
        )
        return cls(
            provider_name=_non_empty_text(_required(data, "provider_name"), "provider_name"),
            provider_type=_non_empty_text(_required(data, "provider_type"), "provider_type"),
            version=_optional_non_empty_text(data.get("version"), "version"),
            metadata=_plain_mapping(data.get("metadata", {}), "metadata"),
        )


@dataclass(frozen=True, slots=True)
class SweepProviderContext:
    """Context passed into provider proposal streams."""

    sweep_id: str
    sweep_name: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "sweep_id", _non_empty_text(self.sweep_id, "sweep_id"))
        object.__setattr__(
            self,
            "sweep_name",
            _optional_non_empty_text(self.sweep_name, "sweep_name"),
        )
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "sweep_id": self.sweep_id,
            "sweep_name": self.sweep_name,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "SweepProviderContext":
        if not isinstance(data, Mapping):
            raise SweepProtocolError("SweepProviderContext payload must be a mapping")
        _reject_unknown(
            data,
            {"sweep_id", "sweep_name", "metadata"},
            object_name="SweepProviderContext",
        )
        return cls(
            sweep_id=_non_empty_text(_required(data, "sweep_id"), "sweep_id"),
            sweep_name=_optional_non_empty_text(data.get("sweep_name"), "sweep_name"),
            metadata=_plain_mapping(data.get("metadata", {}), "metadata"),
        )


@runtime_checkable
class SweepProposalProvider(Protocol):
    """Contextful provider contract for deterministic trial proposals."""

    @property
    def identity(self) -> SweepProviderIdentity:
        ...

    def proposals(self, context: SweepProviderContext) -> Iterable["TrialProposal"]:
        ...


@runtime_checkable
class FiniteSweepProposalProvider(SweepProposalProvider, Protocol):
    """Optional finite-provider capability."""

    def __len__(self) -> int:
        ...


@dataclass(frozen=True, slots=True)
class TrialProposal:
    """Proposal for a single trial candidate."""

    provider_trial_id: str | None = None
    trial_index: int | None = None
    overrides: Mapping[str, PlainData] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider_trial_id",
            _optional_non_empty_text(self.provider_trial_id, "provider_trial_id"),
        )
        object.__setattr__(
            self, "trial_index", _non_negative_int(self.trial_index, "trial_index")
        )
        object.__setattr__(self, "overrides", _plain_mapping(self.overrides, "overrides"))
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_trial_id": self.provider_trial_id,
            "trial_index": self.trial_index,
            "overrides": dict(self.overrides),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "TrialProposal":
        if not isinstance(data, Mapping):
            raise SweepProtocolError("TrialProposal payload must be a mapping")
        _reject_unknown(
            data,
            {"provider_trial_id", "trial_index", "overrides", "metadata"},
            object_name="TrialProposal",
        )
        trial_index = data.get("trial_index")
        if trial_index is not None:
            _non_negative_int(trial_index, "trial_index")
        return cls(
            provider_trial_id=_optional_non_empty_text(
                data.get("provider_trial_id"), "provider_trial_id"
            ),
            trial_index=cast(int | None, trial_index),
            overrides=_plain_mapping(data.get("overrides", {}), "overrides"),
            metadata=_plain_mapping(data.get("metadata", {}), "metadata"),
        )


def provider_is_finite(provider: object) -> bool:
    """Return True when a provider exposes explicit finite capability."""

    return isinstance(provider, FiniteSweepProposalProvider)


def provider_trial_count(provider: object) -> int | None:
    """Return explicit trial count when available."""

    if isinstance(provider, FiniteSweepProposalProvider):
        value = len(provider)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise SweepProtocolError(
                "__len__ for finite provider must return a non-negative integer"
            )
        return value
    return None


__all__ = [
    "SweepProviderIdentity",
    "SweepProviderContext",
    "SweepProposalProvider",
    "FiniteSweepProposalProvider",
    "TrialProposal",
    "provider_is_finite",
    "provider_trial_count",
]
