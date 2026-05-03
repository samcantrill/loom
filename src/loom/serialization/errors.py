"""Errors for serialization helpers."""

from loom.errors import SerializationError as _SerializationError


__all__ = [
    "SerializationError",
    "DeserializationError",
    "PlainDataError",
    "SchemaVersionError",
]


SerializationError = _SerializationError


class DeserializationError(_SerializationError):
    """Error raised when serialized input cannot be reconstructed."""


class PlainDataError(_SerializationError):
    """Error raised when input is not plain structured data."""


class SchemaVersionError(DeserializationError):
    """Error raised when a schema version is missing or unsupported."""
