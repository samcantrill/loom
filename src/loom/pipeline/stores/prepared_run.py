"""Store-safe validation for prepared-run persistence payloads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from loom.serialization import PlainData, ensure_plain_data
from loom.serialization.errors import PlainDataError
from loom.timestamps import parse_timestamp

from .errors import PreparedRunStorePayloadError

PREPARED_RUN_SCHEMA_VERSION = 1

PREPARED_RUN_CONTINUATION_WHOLE_RUN = "whole_run"

PREPARED_RUN_DOCUMENT_FIELDS = frozenset(
    {
        "schema_version",
        "run_uri",
        "prepared_at",
        "executor_name",
        "continuation_type",
        "plan",
        "config",
        "provenance",
        "runtime",
        "metadata",
    }
)

_CONTINUATION_TYPES = frozenset({PREPARED_RUN_CONTINUATION_WHOLE_RUN})

PREPARED_RUN_PLAN_FIELDS = frozenset(
    {
        "document_ref",
        "plan_digest",
        "plan_path",
        "plan_summary",
    }
)
PREPARED_RUN_CONFIG_FIELDS = frozenset(
    {
        "composition_manifest_ref",
        "raw_snapshot_ref",
        "recipe_manifest_ref",
        "redacted_snapshot_ref",
        "summary",
    }
)
PREPARED_RUN_PROVENANCE_FIELDS = frozenset(
    {
        "command_ref",
        "dependencies_ref",
        "git_ref",
        "summary",
    }
)
PREPARED_RUN_RUNTIME_FIELDS = frozenset(
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
_UNSAFE_METADATA_KINDS = _UNSAFE_FIELD_NAMES | frozenset(
    {
        "raw",
        "raw_adapter",
        "raw_payload",
    }
)


def validate_prepared_run_document(
    value: object,
    *,
    expected_run_uri: str | None = None,
    field: str = "prepared_run",
) -> dict[str, PlainData]:
    """Validate a full prepared-run document before persistence."""

    document = _plain_mapping(cast(Mapping[str, PlainData], value), field)
    extra = set(document) - PREPARED_RUN_DOCUMENT_FIELDS
    missing = PREPARED_RUN_DOCUMENT_FIELDS - set(document)
    if extra:
        raise PreparedRunStorePayloadError(
            _join(field, sorted(extra)[0]),
            "field is not allowed in prepared-run documents",
            category="opaque_payload",
        )
    if missing:
        raise PreparedRunStorePayloadError(
            _join(field, sorted(missing)[0]),
            "required prepared-run document field is missing",
            category="schema",
        )
    if not isinstance(document["schema_version"], int) or isinstance(
        document["schema_version"], bool
    ):
        raise PreparedRunStorePayloadError(
            _join(field, "schema_version"),
            "schema version must be an integer",
            category="schema",
        )
    if document["schema_version"] != PREPARED_RUN_SCHEMA_VERSION:
        raise PreparedRunStorePayloadError(
            _join(field, "schema_version"),
            f"schema version must be {PREPARED_RUN_SCHEMA_VERSION}",
            category="schema",
        )
    _non_empty_string(document["run_uri"], _join(field, "run_uri"))
    if expected_run_uri is not None and document["run_uri"] != expected_run_uri:
        raise PreparedRunStorePayloadError(
            _join(field, "run_uri"),
            f"run URI mismatch: expected {expected_run_uri!r}",
            category="schema",
        )
    _timestamp_string(document["prepared_at"], _join(field, "prepared_at"))
    _non_empty_string(document["executor_name"], _join(field, "executor_name"))
    continuation_type = _non_empty_string(
        document["continuation_type"], _join(field, "continuation_type")
    )
    if continuation_type not in _CONTINUATION_TYPES:
        valid = ", ".join(sorted(_CONTINUATION_TYPES))
        raise PreparedRunStorePayloadError(
            _join(field, "continuation_type"),
            f"continuation type must be one of: {valid}",
            category="schema",
        )

    document["plan"] = validate_prepared_run_summary(
        document["plan"], field=_join(field, "plan"), allowed=PREPARED_RUN_PLAN_FIELDS
    )
    document["config"] = validate_prepared_run_summary(
        document["config"],
        field=_join(field, "config"),
        allowed=PREPARED_RUN_CONFIG_FIELDS,
    )
    document["provenance"] = validate_prepared_run_summary(
        document["provenance"],
        field=_join(field, "provenance"),
        allowed=PREPARED_RUN_PROVENANCE_FIELDS,
    )
    document["runtime"] = validate_prepared_run_summary(
        document["runtime"],
        field=_join(field, "runtime"),
        allowed=PREPARED_RUN_RUNTIME_FIELDS,
    )
    document["metadata"] = validate_prepared_run_typed_metadata(
        document["metadata"], field=_join(field, "metadata")
    )
    return document


def validate_prepared_run_summary(
    value: object,
    *,
    field: str,
    allowed: frozenset[str],
) -> dict[str, PlainData]:
    """Validate one prepared-run safe summary section."""

    mapping = _plain_mapping(cast(Mapping[str, PlainData], value), field)
    extra = set(mapping) - allowed
    if extra:
        raise PreparedRunStorePayloadError(
            _join(field, sorted(extra)[0]),
            "field is not an allowed prepared-run summary category",
            category="opaque_payload",
        )
    _reject_unsafe_payload(mapping, field=field)
    return mapping


def validate_prepared_run_typed_metadata(
    value: object,
    *,
    field: str,
) -> dict[str, PlainData]:
    """Validate explicitly typed safe prepared-run metadata entries."""

    mapping = _plain_mapping(cast(Mapping[str, PlainData], value), field)
    for name, entry in mapping.items():
        entry_field = _join(field, name)
        if _unsafe_name(name):
            raise PreparedRunStorePayloadError(
                entry_field,
                "metadata key is reserved for unsafe prepared-run payloads",
                category="unsafe_field",
            )
        if name == "plugin_activations":
            if not isinstance(entry, dict):
                raise PreparedRunStorePayloadError(
                    entry_field,
                    "plugin activation metadata must be a mapping",
                    category="opaque_payload",
                )
            continue
        if not isinstance(entry, dict):
            raise PreparedRunStorePayloadError(
                entry_field,
                "metadata entries must be typed mappings with a kind field",
                category="opaque_payload",
            )
        extra = set(entry) - _METADATA_ENTRY_FIELDS
        if extra:
            raise PreparedRunStorePayloadError(
                _join(entry_field, sorted(extra)[0]),
                "metadata entries may only contain kind and data",
                category="opaque_payload",
            )
        kind = entry.get("kind")
        if not isinstance(kind, str) or not kind:
            raise PreparedRunStorePayloadError(
                _join(entry_field, "kind"),
                "metadata entry kind must be a non-empty string",
                category="opaque_payload",
            )
        if _unsafe_metadata_kind(kind):
            raise PreparedRunStorePayloadError(
                _join(entry_field, "kind"),
                "metadata entry kind is reserved for unsafe prepared-run payloads",
                category="unsafe_field",
            )
    _reject_unsafe_payload(mapping, field=field)
    return mapping


def _reject_unsafe_payload(value: PlainData, *, field: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_field = _join(field, key)
            if _unsafe_name(key):
                raise PreparedRunStorePayloadError(
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


def _unsafe_metadata_kind(value: str) -> bool:
    normalized = value.strip().lower().replace("-", "_")
    return normalized in _UNSAFE_METADATA_KINDS


def _plain_mapping(value: Mapping[str, PlainData], field: str) -> dict[str, PlainData]:
    try:
        plain = ensure_plain_data(value, path=field)
    except PlainDataError as exc:
        raise PreparedRunStorePayloadError(
            field,
            str(exc),
            category="plain_data",
        ) from exc
    if not isinstance(plain, dict):
        raise PreparedRunStorePayloadError(
            field,
            "value must be a mapping",
            category="plain_data",
        )
    return plain


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise PreparedRunStorePayloadError(
            field,
            "value must be a non-empty string",
            category="schema",
        )
    return value


def _timestamp_string(value: object, field: str) -> str:
    timestamp = _non_empty_string(value, field)
    try:
        parse_timestamp(timestamp)
    except ValueError as exc:
        raise PreparedRunStorePayloadError(
            field,
            "value must be an ISO 8601 UTC timestamp",
            category="schema",
        ) from exc
    return timestamp


def _join(prefix: str, field: str) -> str:
    if not prefix:
        return field
    return f"{prefix}.{field}"


__all__ = [
    "PREPARED_RUN_CONTINUATION_WHOLE_RUN",
    "PREPARED_RUN_CONFIG_FIELDS",
    "PREPARED_RUN_DOCUMENT_FIELDS",
    "PREPARED_RUN_PLAN_FIELDS",
    "PREPARED_RUN_PROVENANCE_FIELDS",
    "PREPARED_RUN_RUNTIME_FIELDS",
    "PREPARED_RUN_SCHEMA_VERSION",
    "validate_prepared_run_document",
    "validate_prepared_run_summary",
    "validate_prepared_run_typed_metadata",
]
