"""Unit tests for config secret redaction."""

from copy import deepcopy

from weave.redaction import redact_secrets
from loom.serialization import PlainData


def test_redact_secret_like_keys_recursively() -> None:
    resolved: dict[str, PlainData] = {
        "apiKey": "one",
        "nested": {"Private-Key": "two", "safe": "three"},
        "list": [{"TOKEN": "abc"}, {"normal": "ok"}],
    }
    original = deepcopy(resolved)

    redacted = redact_secrets(resolved)

    nested = redacted["nested"]
    assert isinstance(nested, dict)
    items = redacted["list"]
    assert isinstance(items, list)
    first_item = items[0]
    assert isinstance(first_item, dict)

    assert redacted["apiKey"] == "***REDACTED***"
    assert nested["Private-Key"] == "***REDACTED***"
    assert nested["safe"] == "three"
    assert first_item["TOKEN"] == "***REDACTED***"
    assert resolved == original
