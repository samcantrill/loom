"""Unit tests for text codec."""

import pytest

from loom.io.codecs import TextCodec
from loom.io.codecs.errors import CodecDecodeError, CodecEncodeError


def test_text_codec_round_trip() -> None:
    codec = TextCodec()
    encoded = codec.encode("héllo")
    assert encoded == "héllo".encode("utf-8")
    assert codec.decode(encoded) == "héllo"


def test_text_codec_rejects_non_string_values() -> None:
    codec = TextCodec()
    with pytest.raises(CodecEncodeError):
        codec.encode(12)


def test_text_codec_rejects_invalid_bytes_decoding() -> None:
    codec = TextCodec()
    with pytest.raises(CodecDecodeError):
        codec.decode(b"\xff")

