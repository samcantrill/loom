"""Sweep trial value records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from loom.serialization import PlainData, PlainDataError, ensure_plain_data

from .errors import SweepProtocolError


def _plain_mapping(value: object, *, field: str) -> dict[str, PlainData]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise SweepProtocolError(f"{field} must be a mapping")
    try:
        normalized = ensure_plain_data(value, path=field)
    except (PlainDataError, TypeError) as exc:
        raise SweepProtocolError(f"{field} must contain plain data") from exc
    if not isinstance(normalized, dict):
        raise SweepProtocolError(f"{field} must be a mapping")
    return dict(normalized)


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise SweepProtocolError(f"{field} must be a non-empty string")
    return value


def _optional_text(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SweepProtocolError(f"{field} must be a string when set")
    if not value:
        raise SweepProtocolError(f"{field} must be a non-empty string when set")
    return value


def _non_negative_int(value: object, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SweepProtocolError(f"{field} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class SweepTrialRecord:
    """Canonical sweep-trial identity and binding facts."""

    trial_id: str
    trial_index: int
    sweep_id: str
    run_uri: str | None = None
    provider_trial_id: str | None = None
    proposal_overrides: Mapping[str, PlainData] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "trial_id", _text(self.trial_id, field="trial_id"))
        object.__setattr__(
            self, "trial_index", _non_negative_int(self.trial_index, field="trial_index")
        )
        object.__setattr__(self, "sweep_id", _text(self.sweep_id, field="sweep_id"))
        object.__setattr__(
            self, "run_uri", _optional_text(self.run_uri, field="run_uri")
        )
        object.__setattr__(
            self,
            "provider_trial_id",
            _optional_text(self.provider_trial_id, field="provider_trial_id"),
        )
        object.__setattr__(
            self,
            "proposal_overrides",
            _plain_mapping(self.proposal_overrides, field="proposal_overrides"),
        )
        object.__setattr__(
            self,
            "metadata",
            _plain_mapping(self.metadata, field="metadata"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "trial_id": self.trial_id,
            "trial_index": self.trial_index,
            "sweep_id": self.sweep_id,
            "run_uri": self.run_uri,
            "provider_trial_id": self.provider_trial_id,
            "proposal_overrides": dict(self.proposal_overrides),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "SweepTrialRecord":
        if not isinstance(data, Mapping):
            raise SweepProtocolError("SweepTrialRecord payload must be a mapping")
        required = {
            "trial_id",
            "trial_index",
            "sweep_id",
            "run_uri",
            "provider_trial_id",
            "proposal_overrides",
            "metadata",
        }
        unknown = set(data) - required
        if unknown:
            fields = ", ".join(sorted(unknown))
            raise SweepProtocolError(
                f"SweepTrialRecord contains unknown field(s): {fields}"
            )
        return cls(
            trial_id=_text(_required(data, "trial_id"), field="trial_id"),
            trial_index=_non_negative_int(_required(data, "trial_index"), field="trial_index"),
            sweep_id=_text(_required(data, "sweep_id"), field="sweep_id"),
            run_uri=_optional_text(data.get("run_uri"), field="run_uri"),
            provider_trial_id=_optional_text(
                data.get("provider_trial_id"),
                field="provider_trial_id",
            ),
            proposal_overrides=_plain_mapping(
                data.get("proposal_overrides", {}), field="proposal_overrides"
            ),
            metadata=_plain_mapping(data.get("metadata", {}), field="metadata"),
        )


def _normalize_records(
    values: Sequence[object], *, field: str
) -> tuple[SweepTrialRecord, ...]:
    normalized: list[SweepTrialRecord] = []
    for index, value in enumerate(values):
        if isinstance(value, SweepTrialRecord):
            normalized.append(value)
            continue
        if not isinstance(value, Mapping):
            raise SweepProtocolError(
                f"{field}[{index}] must be a mapping or SweepTrialRecord"
            )
        normalized.append(SweepTrialRecord.from_dict(value))
    return tuple(normalized)


def _required(mapping: Mapping[str, object], field_name: str) -> object:
    if field_name not in mapping:
        raise SweepProtocolError(f"missing required field {field_name!r}")
    return mapping[field_name]


__all__ = [
    "SweepTrialRecord",
]
