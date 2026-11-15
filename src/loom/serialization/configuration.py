"""Versioned configuration snapshots; generic protocol JSON remains unchanged."""

from __future__ import annotations

from typing import cast

from weave.errors import ConfigError
from weave.ordered import decode_ordered_config, encode_ordered_config

from .errors import DeserializationError
from .json import json_dumps_pretty, json_loads
from .plain import PlainData, thaw_plain_data


def configuration_json(value: object) -> str:
    """Serialize authored mapping/sequence order in an explicit wire envelope."""
    return json_dumps_pretty(encode_ordered_config(thaw_plain_data(value)))


def read_configuration_json(text: str, *, path: str = "$") -> dict[str, PlainData]:
    """Read current snapshots or unchanged legacy plain mappings.

    Legacy object order is only the observed retained order; it is never inferred
    to be the original authored order. Current envelopes validate their exact
    version before decoding and cannot silently downgrade to a plain mapping.
    """
    value = json_loads(text, path=path)
    if isinstance(value, dict) and isinstance(value.get("schema"), str) and value["schema"].startswith("weave.ordered-config."):
        try:
            value = decode_ordered_config(value)
        except ConfigError as exc:
            raise DeserializationError(f"Invalid ordered configuration at {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DeserializationError(f"Configuration snapshot must contain a mapping at {path}")
    return cast(dict[str, PlainData], value)
