"""Serialization helpers for plain structured data and JSON."""

from __future__ import annotations

from loom.errors import SerializationError

from loom.serialization.dataclasses import dataclass_from_dict, dataclass_to_dict
from loom.serialization.errors import DeserializationError, PlainDataError, SchemaVersionError
from loom.serialization.json import json_dumps_pretty, json_loads, stable_json_bytes, stable_json_dumps
from loom.serialization.plain import PlainData, ensure_plain_data, is_plain_data, to_plain_data
from loom.serialization.schema import check_supported_schema, get_schema_version, require_schema_version

__all__ = [
    "PlainData",
    "SerializationError",
    "DeserializationError",
    "PlainDataError",
    "SchemaVersionError",
    "is_plain_data",
    "ensure_plain_data",
    "to_plain_data",
    "dataclass_to_dict",
    "dataclass_from_dict",
    "stable_json_dumps",
    "stable_json_bytes",
    "json_dumps_pretty",
    "json_loads",
    "get_schema_version",
    "require_schema_version",
    "check_supported_schema",
]
