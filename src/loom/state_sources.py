"""Shared read-only state source labels for diagnostics surfaces."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from loom.serialization import PlainData, ensure_plain_data
from loom.serialization.errors import PlainDataError


class StateSourceLabel(StrEnum):
    """Stable source labels for user-visible diagnostic state."""

    AUTHORITATIVE_SERVICE = "authoritative_service_truth"
    REGISTRY_HINT = "registry_hint"
    MATERIALIZED_LOCAL = "materialized_local_state"
    DEFERRED_FINALIZATION = "deferred_finalization_state"
    OFFLINE_EVIDENCE = "offline_evidence"
    UNAVAILABLE_AUTHORITY = "unavailable_authority"
    UNKNOWN = "unknown"


class StateSourcePolicy(StrEnum):
    """Stable policy labels for read-only state selection."""

    ONLINE_AUTHORITY = "online_authority"
    LOCAL_MATERIALIZATION = "local_materialization"
    OFFLINE_FIRST = "offline_first"
    DEFERRED_FINALIZATION = "deferred_finalization"
    UNAVAILABLE_AUTHORITY = "unavailable_authority"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class StateSource:
    """Plain-data description of where a displayed state snapshot came from."""

    label: StateSourceLabel | str
    description: str
    authoritative: bool
    policy: StateSourcePolicy | str
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "label", _enum(self.label, StateSourceLabel, "label"))
        object.__setattr__(
            self,
            "policy",
            _enum(self.policy, StateSourcePolicy, "policy"),
        )
        if not isinstance(self.description, str) or self.description == "":
            raise ValueError("description must be a non-empty string")
        if not isinstance(self.authoritative, bool):
            raise ValueError("authoritative must be a bool")
        try:
            details = ensure_plain_data(dict(self.details), path="details")
        except PlainDataError as exc:
            raise ValueError(f"details must be plain-data compatible: {exc}") from exc
        if not isinstance(details, dict):
            raise ValueError("details must serialize to a mapping")
        object.__setattr__(self, "details", details)

    def to_dict(self) -> dict[str, PlainData]:
        label = cast(StateSourceLabel, self.label)
        policy = cast(StateSourcePolicy, self.policy)
        return {
            "label": label.value,
            "description": self.description,
            "authoritative": self.authoritative,
            "policy": policy.value,
            "details": dict(self.details),
        }


def authoritative_service_source(
    *,
    backend_name: str | None = None,
    authority: Mapping[str, PlainData] | None = None,
    reference_source: str | None = None,
) -> dict[str, PlainData]:
    details: dict[str, PlainData] = {}
    if backend_name:
        details["backend_name"] = backend_name
    if authority is not None:
        details["authority"] = dict(authority)
    if reference_source:
        details["reference_source"] = reference_source
    return StateSource(
        label=StateSourceLabel.AUTHORITATIVE_SERVICE,
        description="state read from the selected authority backend",
        authoritative=True,
        policy=StateSourcePolicy.ONLINE_AUTHORITY,
        details=details,
    ).to_dict()


def registry_hint_source(
    *,
    authority: Mapping[str, PlainData] | None = None,
) -> dict[str, PlainData]:
    details = {} if authority is None else {"authority": dict(authority)}
    return StateSource(
        label=StateSourceLabel.REGISTRY_HINT,
        description="state derived from an authority registry hint",
        authoritative=False,
        policy=StateSourcePolicy.ONLINE_AUTHORITY,
        details=details,
    ).to_dict()


def local_materialization_source(
    *,
    path: str | None = None,
) -> dict[str, PlainData]:
    details: dict[str, PlainData] = {}
    if path:
        details["path"] = path
    return StateSource(
        label=StateSourceLabel.MATERIALIZED_LOCAL,
        description="state read from local materialized files",
        authoritative=False,
        policy=StateSourcePolicy.LOCAL_MATERIALIZATION,
        details=details,
    ).to_dict()


def deferred_finalization_source() -> dict[str, PlainData]:
    return StateSource(
        label=StateSourceLabel.DEFERRED_FINALIZATION,
        description="state comes from deferred finalization evidence",
        authoritative=False,
        policy=StateSourcePolicy.DEFERRED_FINALIZATION,
    ).to_dict()


def offline_evidence_source() -> dict[str, PlainData]:
    return StateSource(
        label=StateSourceLabel.OFFLINE_EVIDENCE,
        description="state comes from offline evidence that has not been imported",
        authoritative=False,
        policy=StateSourcePolicy.OFFLINE_FIRST,
    ).to_dict()


def unavailable_authority_source(
    *,
    reason: str | None = None,
    authority: Mapping[str, PlainData] | None = None,
) -> dict[str, PlainData]:
    details: dict[str, PlainData] = {}
    if reason:
        details["reason"] = reason
    if authority is not None:
        details["authority"] = dict(authority)
    return StateSource(
        label=StateSourceLabel.UNAVAILABLE_AUTHORITY,
        description="authority was selected but could not be read",
        authoritative=False,
        policy=StateSourcePolicy.UNAVAILABLE_AUTHORITY,
        details=details,
    ).to_dict()


def unknown_source() -> dict[str, PlainData]:
    return StateSource(
        label=StateSourceLabel.UNKNOWN,
        description="state source was not reported",
        authoritative=False,
        policy=StateSourcePolicy.UNKNOWN,
    ).to_dict()


def redacted_authority_summary(config: object | None) -> dict[str, PlainData] | None:
    """Best-effort redacted authority config summary for diagnostics details."""

    if config is None:
        return None
    redacted_dict = getattr(config, "redacted_dict", None)
    if callable(redacted_dict):
        value = redacted_dict()
    else:
        value = {
            "backend_kind": _enum_value(getattr(config, "backend_kind", None)),
            "deployment_profile": _enum_value(
                getattr(config, "deployment_profile", None)
            ),
            "endpoint": getattr(config, "endpoint", None),
            "workspace_id": getattr(config, "workspace_id", None),
            "reference_id": getattr(config, "reference_id", None),
        }
    normalized = ensure_plain_data(value, path="authority")
    if not isinstance(normalized, dict):
        return None
    return dict(normalized)


def _enum_value(value: object) -> PlainData:
    raw = getattr(value, "value", value)
    return raw if isinstance(raw, (str, int, float, bool)) or raw is None else str(raw)


def _enum(value: object, enum_type: type[StateSourceLabel] | type[StateSourcePolicy], field: str):
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)  # type: ignore[call-arg]
    except ValueError as exc:
        raise ValueError(f"unknown {field}: {value!r}") from exc


__all__ = [
    "StateSource",
    "StateSourceLabel",
    "StateSourcePolicy",
    "authoritative_service_source",
    "deferred_finalization_source",
    "local_materialization_source",
    "offline_evidence_source",
    "redacted_authority_summary",
    "registry_hint_source",
    "unavailable_authority_source",
    "unknown_source",
]
