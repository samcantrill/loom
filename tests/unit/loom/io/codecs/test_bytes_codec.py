"""Unit tests for bytes codec."""

import pytest

from loom.io.codecs import BytesCodec
from loom.io.codecs.errors import CodecDecodeError, CodecEncodeError


def test_bytes_codec_round_trip() -> None:
    codec = BytesCodec()
    payload = b"abc"
    assert codec.encode(payload) == payload
    assert codec.decode(payload) == payload


def test_bytes_codec_accepts_bytearray_and_memoryview() -> None:
    codec = BytesCodec()
    payload = bytearray(b"abc")
    assert codec.encode(payload) == b"abc"
    assert codec.decode(memoryview(payload)) == b"abc"


def test_bytes_codec_rejects_non_bytes() -> None:
    codec = BytesCodec()
    with pytest.raises(CodecEncodeError):
        codec.encode("abc")
    with pytest.raises(CodecDecodeError):
        codec.decode("abc")  # type: ignore[arg-type]

