"""Package tests for digest helpers."""

import pytest

from weave.digests import (
    FingerprintInputError,
    InvalidDigestError,
    UnsupportedHashAlgorithmError,
    compare_digests,
    format_digest,
    hash_mapping,
    hash_plain_data,
    hash_text,
    parse_digest,
    validate_digest,
)


pytestmark = pytest.mark.package


def test_hash_determinism_for_plain_data() -> None:
    left = hash_plain_data({"b": 1, "a": 2})
    right = hash_plain_data({"a": 2, "b": 1})
    assert left == right


def test_hash_text_and_mapping_inputs() -> None:
    assert hash_text("hello") == hash_text("hello")
    assert hash_plain_data("hello") == hash_text('"hello"')
    assert hash_text("hello") != hash_plain_data("hello")
    with pytest.raises(FingerprintInputError):
        hash_mapping([("a", 1)])  # type: ignore[arg-type]


def test_digest_validation_and_parsing() -> None:
    value = format_digest("sha256", "A" * 64)
    parsed = parse_digest(value)
    assert parsed.algorithm == "sha256"
    assert parsed.hexdigest == "a" * 64
    assert validate_digest(value) == value

    with pytest.raises(InvalidDigestError):
        validate_digest("sha256:zzz")
    with pytest.raises(UnsupportedHashAlgorithmError):
        validate_digest("md5:" + "a" * 32)


def test_compare_digests_works() -> None:
    left = format_digest("sha256", "1" * 64)
    right = format_digest("sha256", "1" * 64)
    assert compare_digests(left, right)
    assert not compare_digests(left, None)
    with pytest.raises(InvalidDigestError):
        compare_digests("bad", left)
