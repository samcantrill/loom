"""Versioned manifest models and compatibility helpers for deterministic sweeps."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from loom.serialization import PlainData, PlainDataError, ensure_plain_data

from .errors import (
    SweepManifestCompatibilityDiagnostic,
    SweepManifestError,
    SweepProtocolError,
)
from .providers import SweepProviderIdentity
from .trials import SweepTrialRecord

SWEEP_MANIFEST_SCHEMA_VERSION = 1
TRIALS_MANIFEST_SCHEMA_VERSION = 1
SWEEP_MANIFEST_FILE_NAME = "sweep.json"
TRIALS_MANIFEST_FILE_NAME = "trials.json"


def _required(mapping: Mapping[str, object], field_name: str) -> object:
    if field_name not in mapping:
        raise SweepManifestError(f"missing required field {field_name!r}")
    return mapping[field_name]


def _reject_unknown(mapping: Mapping[str, object], allowed: set[str], *, object_name: str) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise SweepManifestError(f"{object_name} payload has unknown field(s): {fields}")


def _non_empty_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise SweepManifestError(f"{field_name} must be a non-empty string")
    return value


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SweepManifestError(f"{field_name} must be a string when set")
    if not value:
        raise SweepManifestError(f"{field_name} must be a non-empty string when set")
    return value


def _non_negative_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SweepManifestError(f"{field_name} must be a non-negative integer")
    return value


def _plain_mapping(value: object, field_name: str) -> dict[str, PlainData]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise SweepManifestError(f"{field_name} must be a mapping")
    try:
        normalized = ensure_plain_data(value, path=field_name)
    except (PlainDataError, TypeError) as exc:
        raise SweepManifestError(f"{field_name} must contain plain data") from exc
    if not isinstance(normalized, dict):
        raise SweepManifestError(f"{field_name} must be a mapping")
    return dict(normalized)


def _schema_version(value: object, *, object_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise SweepManifestError(f"{object_name} schema_version must be an integer")
    if value <= 0:
        raise SweepManifestError(f"{object_name} schema_version must be positive")
    return value


@dataclass(frozen=True, slots=True)
class SweepManifest:
    """Versioned manifest describing a single sweep."""

    sweep_id: str
    provider: SweepProviderIdentity
    created_at: str
    schema_version: int = SWEEP_MANIFEST_SCHEMA_VERSION
    sweep_name: str | None = None
    trial_count: int | None = None
    trials_manifest: str = TRIALS_MANIFEST_FILE_NAME
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != SWEEP_MANIFEST_SCHEMA_VERSION:
            raise SweepManifestError("SweepManifest schema_version mismatch")
        object.__setattr__(self, "sweep_id", _non_empty_text(self.sweep_id, "sweep_id"))
        object.__setattr__(self, "created_at", _non_empty_text(self.created_at, "created_at"))
        object.__setattr__(
            self, "sweep_name", _optional_text(self.sweep_name, "sweep_name")
        )
        object.__setattr__(self, "trial_count", _non_negative_int(self.trial_count, "trial_count"))
        if not isinstance(self.provider, SweepProviderIdentity):
            raise SweepManifestError("provider must be a SweepProviderIdentity")
        object.__setattr__(
            self, "trials_manifest", _non_empty_text(self.trials_manifest, "trials_manifest")
        )
        object.__setattr__(
            self, "metadata", _plain_mapping(self.metadata, "metadata")
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "sweep_id": self.sweep_id,
            "sweep_name": self.sweep_name,
            "provider": self.provider.to_dict(),
            "created_at": self.created_at,
            "trial_count": self.trial_count,
            "trials_manifest": self.trials_manifest,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "SweepManifest":
        if not isinstance(data, Mapping):
            raise SweepManifestError("SweepManifest payload must be a mapping")
        _reject_unknown(
            data,
            {
                "schema_version",
                "sweep_id",
                "sweep_name",
                "provider",
                "created_at",
                "trial_count",
                "trials_manifest",
                "metadata",
            },
            object_name="SweepManifest",
        )
        schema = _schema_version(_required(data, "schema_version"), object_name="SweepManifest")
        if schema != SWEEP_MANIFEST_SCHEMA_VERSION:
            raise SweepManifestError(f"unsupported SweepManifest schema_version {schema}")
        provider = data.get("provider")
        if not isinstance(provider, Mapping):
            raise SweepManifestError("provider must be a mapping")
        return cls(
            schema_version=schema,
            sweep_id=_non_empty_text(_required(data, "sweep_id"), "sweep_id"),
            provider=SweepProviderIdentity.from_dict(provider),
            created_at=_non_empty_text(_required(data, "created_at"), "created_at"),
            sweep_name=_optional_text(data.get("sweep_name"), "sweep_name"),
            trial_count=_non_negative_int(data.get("trial_count"), "trial_count"),
            trials_manifest=_non_empty_text(
                data.get("trials_manifest", TRIALS_MANIFEST_FILE_NAME),
                "trials_manifest",
            ),
            metadata=_plain_mapping(data.get("metadata", {}), "metadata"),
        )


@dataclass(frozen=True, slots=True)
class TrialsManifest:
    """Versioned manifest for all trial records."""

    sweep_id: str
    trials: tuple[SweepTrialRecord, ...]
    schema_version: int = TRIALS_MANIFEST_SCHEMA_VERSION
    generated_at: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != TRIALS_MANIFEST_SCHEMA_VERSION:
            raise SweepManifestError("TrialsManifest schema_version mismatch")
        object.__setattr__(self, "sweep_id", _non_empty_text(self.sweep_id, "sweep_id"))
        object.__setattr__(
            self,
            "trials",
            tuple(_coerce_trials(self.trials, "trials")),
        )
        object.__setattr__(
            self,
            "generated_at",
            _optional_text(self.generated_at, "generated_at"),
        )
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "sweep_id": self.sweep_id,
            "trials": [trial.to_dict() for trial in self.trials],
            "generated_at": self.generated_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "TrialsManifest":
        if not isinstance(data, Mapping):
            raise SweepManifestError("TrialsManifest payload must be a mapping")
        _reject_unknown(
            data,
            {
                "schema_version",
                "sweep_id",
                "trials",
                "generated_at",
                "metadata",
            },
            object_name="TrialsManifest",
        )
        schema = _schema_version(_required(data, "schema_version"), object_name="TrialsManifest")
        if schema != TRIALS_MANIFEST_SCHEMA_VERSION:
            raise SweepManifestError(f"unsupported TrialsManifest schema_version {schema}")
        trials_data = _required(data, "trials")
        if not isinstance(trials_data, list) and not isinstance(trials_data, tuple):
            raise SweepManifestError("trials must be an array")
        trials: list[SweepTrialRecord] = []
        for index, trial_data in enumerate(trials_data):
            try:
                trial = (
                    trial_data
                    if isinstance(trial_data, SweepTrialRecord)
                    else SweepTrialRecord.from_dict(trial_data)
                )
            except (SweepManifestError, SweepProtocolError) as exc:
                raise SweepManifestError(
                    f"invalid trial record at index {index} in TrialsManifest"
                ) from exc
            trials.append(trial)
        return cls(
            schema_version=schema,
            sweep_id=_non_empty_text(_required(data, "sweep_id"), "sweep_id"),
            trials=tuple(trials),
            generated_at=_optional_text(data.get("generated_at"), "generated_at"),
            metadata=_plain_mapping(data.get("metadata", {}), "metadata"),
        )


def _coerce_trials(
    values: tuple[SweepTrialRecord, ...] | list[SweepTrialRecord | Mapping[str, object]] | tuple[object, ...] | list[object],
    field: str,
) -> tuple[SweepTrialRecord, ...]:
    normalized: list[SweepTrialRecord] = []
    for value in values:
        if isinstance(value, SweepTrialRecord):
            normalized.append(value)
            continue
        if not isinstance(value, Mapping):
            raise SweepManifestError(f"{field} must be SweepTrialRecord values or mappings")
        normalized.append(SweepTrialRecord.from_dict(value))
    return tuple(normalized)


def _compatibility_detail(
    sweep_dir: str,
    manifest_name: str,
    code: str,
    message: str,
    *,
    schema_version: int | None = None,
    trial_id: str | None = None,
    sweep_id: str | None = None,
) -> SweepManifestCompatibilityDiagnostic:
    detail: dict[str, PlainData] = {
        "manifest_name": manifest_name,
    }
    if schema_version is not None:
        detail["schema_version"] = schema_version
    if trial_id is not None:
        detail["trial_id"] = trial_id
    if sweep_id is not None:
        detail["sweep_id"] = sweep_id
    return SweepManifestCompatibilityDiagnostic(
        code=code,
        sweep_dir=sweep_dir,
        manifest_name=manifest_name,
        message=message,
        detail=detail,
    )


def _check_schema_version(
    payload: Mapping[str, object],
    *,
    expected: int,
    sweep_dir: str,
    manifest_name: str,
    manifest_type: str,
) -> tuple[int | None, tuple[SweepManifestCompatibilityDiagnostic, ...]]:
    raw_version = payload.get("schema_version")
    if raw_version is None:
        return None, (
            _compatibility_detail(
                sweep_dir,
                manifest_name,
                f"{manifest_type}_schema_version_missing",
                f"{manifest_type} payload is missing schema_version",
            ),
        )
    try:
        version = _schema_version(raw_version, object_name=f"{manifest_type} schema_version")
    except SweepManifestError as exc:
        raw_sweep_id = payload.get("sweep_id")
        sweep_id: str | None = raw_sweep_id if isinstance(raw_sweep_id, str) else None
        return None, (
            _compatibility_detail(
                sweep_dir,
                manifest_name,
                f"unsupported_{manifest_type}_schema_version",
                str(exc),
                schema_version=cast(int, raw_version) if isinstance(raw_version, int) else None,
                sweep_id=sweep_id,
            ),
        )
    if version != expected:
        return version, (
            _compatibility_detail(
                sweep_dir,
                manifest_name,
                f"unsupported_{manifest_type}_schema_version",
                f"{manifest_type} uses unsupported schema_version {version}, expected {expected}",
                schema_version=version,
            ),
        )
    return version, ()


def check_sweep_manifest_payload(
    payload: object, *, sweep_dir: str
) -> tuple[SweepManifest | None, tuple[SweepManifestCompatibilityDiagnostic, ...]]:
    if not isinstance(payload, Mapping):
        return None, (
            _compatibility_detail(
                sweep_dir,
                SWEEP_MANIFEST_FILE_NAME,
                "malformed_sweep_manifest_payload",
                "sweep manifest payload must be a mapping",
            ),
        )
    version, diagnostics = _check_schema_version(
        payload,
        expected=SWEEP_MANIFEST_SCHEMA_VERSION,
        sweep_dir=sweep_dir,
        manifest_name=SWEEP_MANIFEST_FILE_NAME,
        manifest_type="sweep",
    )
    if diagnostics:
        return None, diagnostics
    try:
        manifest = SweepManifest.from_dict(payload)
    except (SweepManifestError, SweepProtocolError) as exc:
        return None, (
            _compatibility_detail(
                sweep_dir,
                SWEEP_MANIFEST_FILE_NAME,
                "malformed_sweep_manifest",
                str(exc),
                schema_version=version,
            ),
        )
    return manifest, ()


def check_trials_manifest_payload(
    payload: object, *, sweep_dir: str, sweep_id: str | None = None
) -> tuple[TrialsManifest | None, tuple[SweepManifestCompatibilityDiagnostic, ...]]:
    if not isinstance(payload, Mapping):
        return None, (
            _compatibility_detail(
                sweep_dir,
                TRIALS_MANIFEST_FILE_NAME,
                "malformed_trials_manifest_payload",
                "trials manifest payload must be a mapping",
            ),
        )
    version, diagnostics = _check_schema_version(
        payload,
        expected=TRIALS_MANIFEST_SCHEMA_VERSION,
        sweep_dir=sweep_dir,
        manifest_name=TRIALS_MANIFEST_FILE_NAME,
        manifest_type="trials",
    )
    if diagnostics:
        return None, diagnostics
    try:
        manifest = TrialsManifest.from_dict(payload)
    except (SweepManifestError, SweepProtocolError) as exc:
        return None, (
            _compatibility_detail(
                sweep_dir,
                TRIALS_MANIFEST_FILE_NAME,
                "malformed_trials_manifest",
                str(exc),
                schema_version=version,
                sweep_id=sweep_id,
            ),
        )
    if sweep_id is not None and manifest.sweep_id != sweep_id:
        return (
            None,
            (
                _compatibility_detail(
                    sweep_dir,
                    TRIALS_MANIFEST_FILE_NAME,
                    "sweep_id_mismatch",
                (
                    f"trials manifest sweep_id {manifest.sweep_id!r} does not "
                    f"match expected {sweep_id!r}"
                ),
                schema_version=version,
                sweep_id=sweep_id,
            ),
        ),
    )
    return manifest, ()


def read_sweep_manifest(path: str | Path) -> SweepManifest:
    payload = _read_json_payload(path)
    manifest, diagnostics = check_sweep_manifest_payload(
        payload, sweep_dir=str(Path(path).parent)
    )
    if diagnostics:
        message = "; ".join(diagnostic.code for diagnostic in diagnostics)
        raise SweepManifestError(message)
    if manifest is None:
        raise SweepManifestError("failed to read sweep manifest")
    return manifest


def read_trials_manifest(path: str | Path, *, sweep_id: str | None = None) -> TrialsManifest:
    payload = _read_json_payload(path)
    manifest, diagnostics = check_trials_manifest_payload(
        payload, sweep_dir=str(Path(path).parent), sweep_id=sweep_id
    )
    if diagnostics:
        message = "; ".join(diagnostic.code for diagnostic in diagnostics)
        raise SweepManifestError(message)
    if manifest is None:
        raise SweepManifestError("failed to read trials manifest")
    return manifest


def write_sweep_manifest(manifest: SweepManifest, path: str | Path) -> None:
    _write_json_payload(path, manifest.to_dict())


def write_trials_manifest(manifest: TrialsManifest, path: str | Path) -> None:
    _write_json_payload(path, manifest.to_dict())


def _read_json_payload(path: str | Path) -> Mapping[str, object]:
    raw_path = Path(path)
    with raw_path.open("r", encoding="utf-8") as file_handle:
        payload = json.load(file_handle)
    if not isinstance(payload, Mapping):
        raise SweepManifestError(f"manifest at {raw_path} must be a JSON object")
    return payload


def _write_json_payload(path: str | Path, payload: Mapping[str, object]) -> None:
    raw_path = Path(path)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    with raw_path.open("w", encoding="utf-8") as file_handle:
        json.dump(payload, file_handle, indent=2, sort_keys=True)


__all__ = [
    "SWEEP_MANIFEST_SCHEMA_VERSION",
    "TRIALS_MANIFEST_SCHEMA_VERSION",
    "SWEEP_MANIFEST_FILE_NAME",
    "TRIALS_MANIFEST_FILE_NAME",
    "SweepManifest",
    "TrialsManifest",
    "check_sweep_manifest_payload",
    "check_trials_manifest_payload",
    "read_sweep_manifest",
    "read_trials_manifest",
    "write_sweep_manifest",
    "write_trials_manifest",
]
