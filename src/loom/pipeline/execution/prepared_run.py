"""Prepared-run metadata contracts for durable run continuation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from loom.serialization import PlainData, ensure_plain_data, load_versioned_document
from loom.serialization.errors import PlainDataError, SchemaVersionError

from .errors import RunRequestError

PREPARED_RUN_SCHEMA_VERSION = 1

PREPARED_RUN_CONTINUATION_WHOLE_RUN = "whole_run"

_CONTINUATION_TYPES = frozenset({PREPARED_RUN_CONTINUATION_WHOLE_RUN})

_PLAN_FIELDS = frozenset(
    {
        "document_ref",
        "plan_digest",
        "plan_path",
        "plan_summary",
    }
)
_CONFIG_FIELDS = frozenset(
    {
        "composition_manifest_ref",
        "raw_snapshot_ref",
        "recipe_manifest_ref",
        "redacted_snapshot_ref",
        "summary",
    }
)
_PROVENANCE_FIELDS = frozenset(
    {
        "command_ref",
        "dependencies_ref",
        "git_ref",
        "summary",
    }
)
_RUNTIME_FIELDS = frozenset(
    {
        "document_ref",
        "executor",
        "executor_kind",
        "resource_summary",
        "stage_count",
        "stage_executor_summary",
    }
)
_METADATA_ENTRY_FIELDS = frozenset({"kind", "data"})

_UNSAFE_FIELD_NAMES = frozenset(
    {
        "adapter_payload",
        "adapter_payloads",
        "api_key",
        "apikey",
        "credential",
        "credentials",
        "env",
        "env_key",
        "env_keys",
        "env_name",
        "env_names",
        "env_value",
        "env_values",
        "env_var",
        "env_vars",
        "environment",
        "environment_key",
        "environment_keys",
        "environment_name",
        "environment_names",
        "environment_value",
        "environment_values",
        "environment_variable",
        "environment_variables",
        "job_id",
        "job_ids",
        "password",
        "raw_adapter_payload",
        "raw_adapter_payloads",
        "resolved",
        "resolved_config",
        "resolved_environment",
        "resolved_runtime",
        "resolved_value",
        "resolved_values",
        "resolver_output",
        "resolver_outputs",
        "scheduler",
        "scheduler_fact",
        "scheduler_facts",
        "scheduler_job_id",
        "scheduler_job_ids",
        "secret",
        "secrets",
        "slurm_job_id",
        "token",
        "tokens",
    }
)


class PreparedRunPayloadError(RunRequestError):
    """Structured error raised when prepared-run metadata is unsafe."""

    def __init__(self, field: str, reason: str, *, category: str) -> None:
        self.field = field
        self.reason = reason
        self.category = category
        super().__init__(
            f"unsafe prepared-run payload at {field}: {reason} ({category})"
        )


@dataclass(frozen=True, slots=True)
class PreparedRunRecord:
    """Schema-versioned, artifact-safe run preparation metadata."""

    schema_version: int
    run_uri: str
    prepared_at: str
    executor_name: str
    continuation_type: str
    plan: Mapping[str, PlainData] = field(default_factory=dict)
    config: Mapping[str, PlainData] = field(default_factory=dict)
    provenance: Mapping[str, PlainData] = field(default_factory=dict)
    runtime: Mapping[str, PlainData] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != PREPARED_RUN_SCHEMA_VERSION:
            raise RunRequestError("PreparedRunRecord.schema_version must be 1")
        if not isinstance(self.run_uri, str) or not self.run_uri:
            raise RunRequestError("PreparedRunRecord.run_uri must be a non-empty string")
        if not isinstance(self.prepared_at, str) or not self.prepared_at:
            raise RunRequestError(
                "PreparedRunRecord.prepared_at must be a non-empty string"
            )
        if not isinstance(self.executor_name, str) or not self.executor_name:
            raise RunRequestError(
                "PreparedRunRecord.executor_name must be a non-empty string"
            )
        if self.continuation_type not in _CONTINUATION_TYPES:
            valid = ", ".join(sorted(_CONTINUATION_TYPES))
            raise RunRequestError(
                "PreparedRunRecord.continuation_type must be one of: " + valid
            )
        object.__setattr__(
            self, "plan", _safe_mapping(self.plan, field="plan", allowed=_PLAN_FIELDS)
        )
        object.__setattr__(
            self,
            "config",
            _safe_mapping(self.config, field="config", allowed=_CONFIG_FIELDS),
        )
        object.__setattr__(
            self,
            "provenance",
            _safe_mapping(
                self.provenance, field="provenance", allowed=_PROVENANCE_FIELDS
            ),
        )
        object.__setattr__(
            self,
            "runtime",
            _safe_mapping(self.runtime, field="runtime", allowed=_RUNTIME_FIELDS),
        )
        object.__setattr__(
            self, "metadata", _safe_typed_metadata(self.metadata, field="metadata")
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "run_uri": self.run_uri,
            "prepared_at": self.prepared_at,
            "executor_name": self.executor_name,
            "continuation_type": self.continuation_type,
            "plan": dict(self.plan),
            "config": dict(self.config),
            "provenance": dict(self.provenance),
            "runtime": dict(self.runtime),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "PreparedRunRecord":
        try:
            mapping = load_versioned_document(
                data,
                current_version=PREPARED_RUN_SCHEMA_VERSION,
                required={
                    "run_uri",
                    "prepared_at",
                    "executor_name",
                    "continuation_type",
                },
                optional={"plan", "config", "provenance", "runtime", "metadata"},
            )
        except SchemaVersionError as exc:
            raise RunRequestError(f"PreparedRunRecord.from_dict: {exc}") from exc
        return cls(
            schema_version=_int(mapping["schema_version"], "schema_version"),
            run_uri=_str(mapping["run_uri"], "run_uri"),
            prepared_at=_str(mapping["prepared_at"], "prepared_at"),
            executor_name=_str(mapping["executor_name"], "executor_name"),
            continuation_type=_str(mapping["continuation_type"], "continuation_type"),
            plan=_plain_mapping(
                cast(Mapping[str, PlainData], mapping.get("plan", {})),
                "plan",
            ),
            config=_plain_mapping(
                cast(Mapping[str, PlainData], mapping.get("config", {})),
                "config",
            ),
            provenance=_plain_mapping(
                cast(Mapping[str, PlainData], mapping.get("provenance", {})),
                "provenance",
            ),
            runtime=_plain_mapping(
                cast(Mapping[str, PlainData], mapping.get("runtime", {})),
                "runtime",
            ),
            metadata=_plain_mapping(
                cast(Mapping[str, PlainData], mapping.get("metadata", {})),
                "metadata",
            ),
        )


def _safe_mapping(
    value: Mapping[str, PlainData],
    *,
    field: str,
    allowed: frozenset[str],
) -> dict[str, PlainData]:
    mapping = _plain_mapping(value, field)
    extra = set(mapping) - allowed
    if extra:
        raise PreparedRunPayloadError(
            f"{field}.{sorted(extra)[0]}",
            "field is not an allowed prepared-run summary category",
            category="opaque_payload",
        )
    _reject_unsafe_payload(mapping, field=field)
    return mapping


def _safe_typed_metadata(
    value: Mapping[str, PlainData],
    *,
    field: str,
) -> dict[str, PlainData]:
    mapping = _plain_mapping(value, field)
    for name, entry in mapping.items():
        entry_field = f"{field}.{name}"
        if _unsafe_name(name):
            raise PreparedRunPayloadError(
                entry_field,
                "metadata key is reserved for unsafe prepared-run payloads",
                category="unsafe_field",
            )
        if not isinstance(entry, dict):
            raise PreparedRunPayloadError(
                entry_field,
                "metadata entries must be typed mappings with a kind field",
                category="opaque_payload",
            )
        extra = set(entry) - _METADATA_ENTRY_FIELDS
        if extra:
            raise PreparedRunPayloadError(
                f"{entry_field}.{sorted(extra)[0]}",
                "metadata entries may only contain kind and data",
                category="opaque_payload",
            )
        kind = entry.get("kind")
        if not isinstance(kind, str) or not kind:
            raise PreparedRunPayloadError(
                f"{entry_field}.kind",
                "metadata entry kind must be a non-empty string",
                category="opaque_payload",
            )
    _reject_unsafe_payload(mapping, field=field)
    return mapping


def _reject_unsafe_payload(value: PlainData, *, field: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_field = f"{field}.{key}"
            if _unsafe_name(key):
                raise PreparedRunPayloadError(
                    key_field,
                    "field is reserved for secret-bearing or scheduler payloads",
                    category="unsafe_field",
                )
            _reject_unsafe_payload(item, field=key_field)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_unsafe_payload(item, field=f"{field}[{index}]")


def _unsafe_name(value: str) -> bool:
    normalized = value.strip().lower().replace("-", "_")
    return normalized in _UNSAFE_FIELD_NAMES


def _plain_mapping(value: Mapping[str, PlainData], path: str) -> dict[str, PlainData]:
    try:
        plain = ensure_plain_data(value, path=path)
    except PlainDataError as exc:
        raise PreparedRunPayloadError(
            path,
            str(exc),
            category="plain_data",
        ) from exc
    if not isinstance(plain, dict):
        raise PreparedRunPayloadError(
            path,
            "value must be a mapping",
            category="plain_data",
        )
    return plain


def _str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise RunRequestError(f"{field} must be a non-empty string")
    return value


def _int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise RunRequestError(f"{field} must be an integer")
    return value


__all__ = [
    "PREPARED_RUN_CONTINUATION_WHOLE_RUN",
    "PREPARED_RUN_SCHEMA_VERSION",
    "PreparedRunPayloadError",
    "PreparedRunRecord",
]
