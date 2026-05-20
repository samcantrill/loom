"""Digest and fingerprint helpers for config artifact helpers."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping

from .json import stable_json_bytes
from .errors import FingerprintInputError, InvalidDigestError, UnsupportedHashAlgorithmError
from .errors import ParsedDigest


def parse_digest(value: str) -> ParsedDigest:
    """Parse and normalize a persisted digest string."""

    validated = validate_digest(value)
    algorithm, hexdigest = validated.split(":", 1)
    return ParsedDigest(algorithm=algorithm, hexdigest=hexdigest)


def validate_digest(value: object, *, algorithms: set[str] | None = None) -> str:
    """Validate a digest string and return normalized representation."""

    if not isinstance(value, str):
        raise InvalidDigestError("Digest must be a string")
    if ":" not in value:
        raise InvalidDigestError(f"Invalid digest syntax: {value!r}")

    algorithm, hexdigest = value.split(":", 1)
    algorithm = _normalise_algorithm(algorithm, algorithms=algorithms)
    _validate_hex(algorithm, hexdigest)
    return f"{algorithm}:{hexdigest.lower()}"


def format_digest(algorithm: str, hexdigest: str) -> str:
    """Return canonical digest syntax."""

    algorithm = _normalise_algorithm(algorithm)
    normalized = hexdigest.lower()
    _validate_hex(algorithm, normalized)
    return f"{algorithm}:{normalized}"


def compare_digests(left: str | None, right: str | None) -> bool:
    """Compare two digest values safely."""

    if left is None or right is None:
        return False
    left_normalized = validate_digest(left)
    right_normalized = validate_digest(right)
    return hmac.compare_digest(left_normalized, right_normalized)


def hash_bytes(data: bytes, *, algorithm: str = "sha256") -> str:
    """Hash bytes and return canonical digest."""

    if not isinstance(data, bytes):
        raise FingerprintInputError("hash_bytes expects bytes")
    normalized = _normalise_algorithm(algorithm)
    hasher = hashlib.new(normalized)
    hasher.update(data)
    return format_digest(normalized, hasher.hexdigest())


def hash_text(text: str, *, algorithm: str = "sha256", encoding: str = "utf-8") -> str:
    """Hash text with explicit encoding."""

    if not isinstance(text, str):
        raise FingerprintInputError("hash_text expects str")
    if not isinstance(encoding, str) or not encoding:
        raise FingerprintInputError("encoding must be a non-empty string")
    return hash_bytes(text.encode(encoding), algorithm=algorithm)


def hash_plain_data(value: object, *, algorithm: str = "sha256") -> str:
    """Hash plain data as stable JSON bytes."""

    return hash_bytes(stable_json_bytes(value), algorithm=algorithm)


def hash_mapping(mapping: object, *, algorithm: str = "sha256") -> str:
    """Hash a mapping using stable JSON serialization."""

    if not isinstance(mapping, Mapping):
        raise FingerprintInputError("hash_mapping expects a mapping")
    return hash_plain_data(mapping, algorithm=algorithm)


def _normalise_algorithm(algorithm: str, *, algorithms: set[str] | None = None) -> str:
    normalized = algorithm.lower()
    allowed = algorithms or {"sha256"}
    if normalized not in allowed:
        raise UnsupportedHashAlgorithmError(f"Unsupported hash algorithm: {algorithm!r}")
    return normalized


def _validate_hex(algorithm: str, hexdigest: str) -> None:
    expected_lengths = {"sha256": 64}
    if algorithm not in expected_lengths:
        raise UnsupportedHashAlgorithmError(f"Unsupported hash algorithm: {algorithm!r}")

    expected = expected_lengths[algorithm]
    if len(hexdigest) != expected:
        raise InvalidDigestError(f"Invalid digest length for {algorithm}: {hexdigest!r}")
    if not all(char in "0123456789abcdef" for char in hexdigest.lower()):
        raise InvalidDigestError(f"Invalid digest hex for {algorithm}: {hexdigest!r}")


__all__ = [
    "ParsedDigest",
    "parse_digest",
    "validate_digest",
    "format_digest",
    "compare_digests",
    "hash_bytes",
    "hash_text",
    "hash_plain_data",
    "hash_mapping",
]
