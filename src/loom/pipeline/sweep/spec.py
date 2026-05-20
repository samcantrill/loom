"""Trusted grid and manual sweep spec records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from loom.serialization import PlainData, PlainDataError, ensure_plain_data, stable_json_dumps

from .errors import SweepProtocolError

SWEEP_SPEC_SCHEMA_VERSION = 1
DEFAULT_MAX_GENERATED_TRIALS = 100


class SweepMode(StrEnum):
    """First-party deterministic sweep modes."""

    GRID = "grid"
    MANUAL = "manual"


def _required(mapping: Mapping[str, object], field_name: str) -> object:
    if field_name not in mapping:
        raise SweepProtocolError(f"missing required field {field_name!r}")
    return mapping[field_name]


def _reject_unknown(mapping: Mapping[str, object], allowed: set[str], *, object_name: str) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise SweepProtocolError(f"{object_name} payload has unknown field(s): {fields}")


def _non_empty_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise SweepProtocolError(f"{field_name} must be a non-empty string")
    return value


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SweepProtocolError(f"{field_name} must be a string when set")
    if not value:
        raise SweepProtocolError(f"{field_name} must be a non-empty string when set")
    return value


def _schema_version(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise SweepProtocolError("schema_version must be an integer")
    if value != SWEEP_SPEC_SCHEMA_VERSION:
        raise SweepProtocolError(f"unsupported sweep spec schema_version {value}")
    return value


def _plain_mapping(value: object, field_name: str) -> dict[str, PlainData]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise SweepProtocolError(f"{field_name} must be a mapping")
    try:
        normalized = ensure_plain_data(value, path=field_name)
    except (PlainDataError, TypeError) as exc:
        raise SweepProtocolError(f"{field_name} must contain plain data") from exc
    if not isinstance(normalized, dict):
        raise SweepProtocolError(f"{field_name} must be a mapping")
    return dict(normalized)


def _positive_or_unlimited(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise SweepProtocolError(f"{field_name} must be a positive integer or null")
    return value


def _axis_values(value: object, field_name: str) -> tuple[PlainData, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise SweepProtocolError(f"{field_name} must be a non-empty sequence")
    if not value:
        raise SweepProtocolError(f"{field_name} must be a non-empty sequence")
    try:
        normalized = ensure_plain_data(list(value), path=field_name)
    except (PlainDataError, TypeError) as exc:
        raise SweepProtocolError(f"{field_name} must contain plain data") from exc
    if not isinstance(normalized, list):
        raise SweepProtocolError(f"{field_name} must be a sequence")
    return tuple(normalized)


def _grid_axes(value: object) -> dict[str, tuple[PlainData, ...]]:
    if not isinstance(value, Mapping):
        raise SweepProtocolError("grid must be a mapping of axis names to values")
    if not value:
        raise SweepProtocolError("grid must define at least one axis")
    axes: dict[str, tuple[PlainData, ...]] = {}
    for raw_name, raw_values in value.items():
        axis_name = _non_empty_text(raw_name, "grid axis name")
        axes[axis_name] = _axis_values(raw_values, f"grid.{axis_name}")
    _validate_override_paths({name: values[0] for name, values in axes.items()})
    return axes


def _manual_trials(value: object) -> tuple["ManualTrialSpec", ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise SweepProtocolError("trials must be a sequence")
    trials: list[ManualTrialSpec] = []
    for index, item in enumerate(value):
        try:
            trial = item if isinstance(item, ManualTrialSpec) else ManualTrialSpec.from_dict(item)
        except SweepProtocolError as exc:
            raise SweepProtocolError(f"invalid manual trial at index {index}: {exc}") from exc
        trials.append(trial)
    if not trials:
        raise SweepProtocolError("manual sweep must define at least one trial")
    return tuple(trials)


def _validate_override_paths(overrides: Mapping[str, PlainData]) -> None:
    for path in overrides:
        _non_empty_text(path, "override path")
        normalized_path = path[1:] if path.startswith("+") else path
        if not normalized_path or any(not segment for segment in normalized_path.split(".")):
            raise SweepProtocolError(f"invalid override path {path!r}")


def _override_expression(path: str, value: PlainData) -> str:
    return f"{path}={stable_json_dumps(value)}"


@dataclass(frozen=True, slots=True)
class ManualTrialSpec:
    """Trusted manual trial proposal input."""

    overrides: Mapping[str, PlainData]
    name: str | None = None
    provider_trial_id: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        overrides = _plain_mapping(self.overrides, "overrides")
        _validate_override_paths(overrides)
        object.__setattr__(self, "overrides", overrides)
        object.__setattr__(self, "name", _optional_text(self.name, "name"))
        object.__setattr__(
            self,
            "provider_trial_id",
            _optional_text(self.provider_trial_id, "provider_trial_id"),
        )
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "name": self.name,
            "provider_trial_id": self.provider_trial_id,
            "overrides": dict(self.overrides),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "ManualTrialSpec":
        if not isinstance(data, Mapping):
            raise SweepProtocolError("ManualTrialSpec payload must be a mapping")
        _reject_unknown(
            data,
            {"name", "provider_trial_id", "overrides", "metadata"},
            object_name="ManualTrialSpec",
        )
        return cls(
            name=_optional_text(data.get("name"), "name"),
            provider_trial_id=_optional_text(data.get("provider_trial_id"), "provider_trial_id"),
            overrides=_plain_mapping(_required(data, "overrides"), "overrides"),
            metadata=_plain_mapping(data.get("metadata", {}), "metadata"),
        )


@dataclass(frozen=True, slots=True)
class GridSweepSpec:
    """Trusted first-party grid sweep spec."""

    sweep_id: str
    grid: Mapping[str, Sequence[PlainData]]
    schema_version: int = SWEEP_SPEC_SCHEMA_VERSION
    sweep_name: str | None = None
    run_uri_root: str | None = None
    max_generated_trials: int | None = DEFAULT_MAX_GENERATED_TRIALS
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))
        object.__setattr__(self, "sweep_id", _non_empty_text(self.sweep_id, "sweep_id"))
        object.__setattr__(self, "sweep_name", _optional_text(self.sweep_name, "sweep_name"))
        object.__setattr__(self, "run_uri_root", _optional_text(self.run_uri_root, "run_uri_root"))
        object.__setattr__(
            self,
            "max_generated_trials",
            _positive_or_unlimited(self.max_generated_trials, "max_generated_trials"),
        )
        object.__setattr__(self, "grid", _grid_axes(self.grid))
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    @property
    def mode(self) -> SweepMode:
        return SweepMode.GRID

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode.value,
            "sweep_id": self.sweep_id,
            "sweep_name": self.sweep_name,
            "run_uri_root": self.run_uri_root,
            "max_generated_trials": self.max_generated_trials,
            "grid": {axis: list(values) for axis, values in self.grid.items()},
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "GridSweepSpec":
        if not isinstance(data, Mapping):
            raise SweepProtocolError("GridSweepSpec payload must be a mapping")
        _reject_unknown(
            data,
            {
                "schema_version",
                "mode",
                "sweep_id",
                "sweep_name",
                "run_uri_root",
                "max_generated_trials",
                "grid",
                "metadata",
            },
            object_name="GridSweepSpec",
        )
        _validate_mode(data.get("mode"), SweepMode.GRID)
        return cls(
            schema_version=_schema_version(data.get("schema_version", SWEEP_SPEC_SCHEMA_VERSION)),
            sweep_id=_non_empty_text(_required(data, "sweep_id"), "sweep_id"),
            sweep_name=_optional_text(data.get("sweep_name"), "sweep_name"),
            run_uri_root=_optional_text(data.get("run_uri_root"), "run_uri_root"),
            max_generated_trials=_positive_or_unlimited(
                data.get("max_generated_trials", DEFAULT_MAX_GENERATED_TRIALS),
                "max_generated_trials",
            ),
            grid=_grid_axes(_required(data, "grid")),
            metadata=_plain_mapping(data.get("metadata", {}), "metadata"),
        )


@dataclass(frozen=True, slots=True)
class ManualSweepSpec:
    """Trusted first-party manual sweep spec."""

    sweep_id: str
    trials: Sequence[ManualTrialSpec]
    schema_version: int = SWEEP_SPEC_SCHEMA_VERSION
    sweep_name: str | None = None
    run_uri_root: str | None = None
    max_generated_trials: int | None = DEFAULT_MAX_GENERATED_TRIALS
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))
        object.__setattr__(self, "sweep_id", _non_empty_text(self.sweep_id, "sweep_id"))
        object.__setattr__(self, "sweep_name", _optional_text(self.sweep_name, "sweep_name"))
        object.__setattr__(self, "run_uri_root", _optional_text(self.run_uri_root, "run_uri_root"))
        object.__setattr__(
            self,
            "max_generated_trials",
            _positive_or_unlimited(self.max_generated_trials, "max_generated_trials"),
        )
        object.__setattr__(self, "trials", _manual_trials(self.trials))
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    @property
    def mode(self) -> SweepMode:
        return SweepMode.MANUAL

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode.value,
            "sweep_id": self.sweep_id,
            "sweep_name": self.sweep_name,
            "run_uri_root": self.run_uri_root,
            "max_generated_trials": self.max_generated_trials,
            "trials": [trial.to_dict() for trial in self.trials],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "ManualSweepSpec":
        if not isinstance(data, Mapping):
            raise SweepProtocolError("ManualSweepSpec payload must be a mapping")
        _reject_unknown(
            data,
            {
                "schema_version",
                "mode",
                "sweep_id",
                "sweep_name",
                "run_uri_root",
                "max_generated_trials",
                "trials",
                "metadata",
            },
            object_name="ManualSweepSpec",
        )
        _validate_mode(data.get("mode"), SweepMode.MANUAL)
        return cls(
            schema_version=_schema_version(data.get("schema_version", SWEEP_SPEC_SCHEMA_VERSION)),
            sweep_id=_non_empty_text(_required(data, "sweep_id"), "sweep_id"),
            sweep_name=_optional_text(data.get("sweep_name"), "sweep_name"),
            run_uri_root=_optional_text(data.get("run_uri_root"), "run_uri_root"),
            max_generated_trials=_positive_or_unlimited(
                data.get("max_generated_trials", DEFAULT_MAX_GENERATED_TRIALS),
                "max_generated_trials",
            ),
            trials=_manual_trials(_required(data, "trials")),
            metadata=_plain_mapping(data.get("metadata", {}), "metadata"),
        )


SweepSpec = GridSweepSpec | ManualSweepSpec


def _validate_mode(value: object, expected: SweepMode) -> None:
    try:
        mode = SweepMode(value) if value is not None else expected
    except ValueError as exc:
        raise SweepProtocolError(f"unsupported sweep mode {value!r}") from exc
    if mode is not expected:
        raise SweepProtocolError(
            f"mode must be {expected.value!r} for {expected.value} sweep specs"
        )


def parse_sweep_spec(data: object) -> SweepSpec:
    """Parse a trusted sweep spec mapping into a first-party spec record."""

    if isinstance(data, (GridSweepSpec, ManualSweepSpec)):
        return data
    if not isinstance(data, Mapping):
        raise SweepProtocolError("sweep spec payload must be a mapping")
    mode = data.get("mode")
    if mode is None:
        raise SweepProtocolError("sweep spec mode is required")
    try:
        parsed_mode = SweepMode(mode)
    except ValueError as exc:
        raise SweepProtocolError(f"unsupported sweep mode {mode!r}") from exc
    if parsed_mode is SweepMode.GRID:
        return GridSweepSpec.from_dict(data)
    return ManualSweepSpec.from_dict(data)


def sweep_spec_to_dict(spec: SweepSpec) -> dict[str, PlainData]:
    """Return normalized plain-data payload for a first-party sweep spec."""

    return spec.to_dict()


__all__ = [
    "DEFAULT_MAX_GENERATED_TRIALS",
    "SWEEP_SPEC_SCHEMA_VERSION",
    "SweepMode",
    "GridSweepSpec",
    "ManualSweepSpec",
    "ManualTrialSpec",
    "SweepSpec",
    "parse_sweep_spec",
    "sweep_spec_to_dict",
]
