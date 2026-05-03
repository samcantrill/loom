"""Unit tests for config secret redaction."""

from copy import deepcopy

from loom.config.redaction import redact_secrets


def test_redact_secret_like_keys_recursively() -> None:
    resolved = {
        "apiKey": "one",
        "nested": {"Private-Key": "two", "safe": "three"},
        "list": [{"TOKEN": "abc"}, {"normal": "ok"}],
    }
    original = deepcopy(resolved)

    redacted = redact_secrets(resolved)

    assert redacted["apiKey"] == "***REDACTED***"
    assert redacted["nested"]["Private-Key"] == "***REDACTED***"
    assert redacted["nested"]["safe"] == "three"
    assert redacted["list"][0]["TOKEN"] == "***REDACTED***"
    assert resolved == original
