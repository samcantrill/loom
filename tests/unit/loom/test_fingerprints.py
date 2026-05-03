"""Unit tests for fingerprint helpers."""

import pytest

from loom.fingerprints import (
    FingerprintComparisonError,
    FingerprintInputError,
    InvalidDigestError,
    UnsupportedHashAlgorithmError,
    hash_bytes,
    compare_digests,
    format_digest,
    hash_mapping,
    hash_plain_data,
    hash_text,
    parse_digest,
    validate_digest,
)


def test_hash_functions_are_deterministic() -> None:
    first = hash_plain_data({"b": 1, "a": 2})
    second = hash_plain_data({"a": 2, "b": 1})
    assert first == second


def test_hash_text_and_mapping_inputs() -> None:
    assert hash_text("hello") == hash_plain_data("hello")
    with pytest.raises(FingerprintInputError):
        hash_mapping([("a", 1)])  # type: ignore[arg-type]


def test_hash_bytes_requires_bytes_only() -> None:
    with pytest.raises(FingerprintInputError):
        hash_bytes(bytearray(b"x"))  # type: ignore[call-arg]


def test_parse_and_validate_digest() -> None:
    value = format_digest("sha256", "A" * 64)
    parsed = parse_digest(value)
    assert parsed.algorithm == "sha256"
    assert len(parsed.hexdigest) == 64
    assert parsed.hexdigest == "a" * 64
    assert validate_digest(value) == value
    with pytest.raises(InvalidDigestError):
        validate_digest("sha256:zzz")
    with pytest.raises(UnsupportedHashAlgorithmError):
        validate_digest("md5:" + "a" * 32)


def test_compare_digests() -> None:
    left = format_digest("sha256", "1" * 64)
    right = format_digest("sha256", "1" * 64)
    assert compare_digests(left, right)
    assert not compare_digests(left, None)


def test_compare_rejects_invalid_inputs() -> None:
    with pytest.raises(InvalidDigestError):
        compare_digests("bad", "sha256:" + "a" * 64)
