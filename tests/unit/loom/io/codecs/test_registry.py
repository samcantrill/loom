"""Unit tests for codec registry."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import pytest

from loom.io.codecs import (
    Codec,
    CodecRegistry,
    CodecRegistrationError,
    JSONCodec,
    create_default_codec_registry,
    UnknownCodecError,
)
from loom.serialization import PlainData


class DummyCodec:
    key = "dummy.v1"

    def encode(self, obj: object, *, metadata: Mapping[str, PlainData] | None = None) -> bytes:
        del metadata
        return b"ok"

    def decode(self, data: bytes, *, metadata: Mapping[str, PlainData] | None = None) -> str:
        del metadata
        if data != b"ok":
            raise ValueError("bad")
        return "ok"


def test_registry_register_duplicate_key_raises() -> None:
    registry = CodecRegistry()
    registry.register(JSONCodec())
    with pytest.raises(CodecRegistrationError):
        registry.register(JSONCodec())


def test_registry_register_invalid_codec_object() -> None:
    class _NotCodec:
        pass

    registry = CodecRegistry()
    with pytest.raises(CodecRegistrationError):
        registry.register(cast(Codec, _NotCodec()))


def test_registry_get_unknown_key_lists_registered() -> None:
    registry = create_default_codec_registry()
    with pytest.raises(UnknownCodecError) as exc:
        registry.get("missing.v1")
    assert "Registered codecs" in str(exc.value)


def test_registry_encode_decode_dispatches() -> None:
    registry = create_default_codec_registry()
    encoded = registry.encode("text.v1", "hello")
    assert registry.decode("text.v1", encoded) == "hello"


def test_registry_keys_are_sorted() -> None:
    registry = create_default_codec_registry()
    assert registry.keys() == ("bytes.v1", "json.v1", "text.v1")


def test_registry_accepts_downstream_codec_without_inheritance() -> None:
    registry = CodecRegistry()
    registry.register(DummyCodec())
    assert registry.decode("dummy.v1", b"ok") == "ok"


def test_default_codec_registry_is_fresh() -> None:
    first = create_default_codec_registry()
    second = create_default_codec_registry()
    assert first is not second
    assert first.keys() == second.keys()
