"""Unit tests for JSON codec."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest

from loom.io.codecs import JSONCodec
from loom.io.codecs.errors import CodecDecodeError, CodecEncodeError


class _Callable:
    def __call__(self) -> str:
        return "value"


@dataclass
class _Point:
    x: int


def test_json_codec_round_trip_pretty_bytes() -> None:
    codec = JSONCodec()
    payload = {"a": [1, 2, True], "nested": {"value": None}}
    encoded = codec.encode(payload)
    assert encoded.endswith(b"\n")
    decoded = codec.decode(encoded)
    assert decoded == payload


@pytest.mark.parametrize(
    "value",
    [
        _Point(1),
        Path("/tmp/file.txt"),
        datetime(2020, 1, 1),
        b"raw-bytes",
        {"items": {1, 2}},
        _Callable(),
    ],
)
def test_json_codec_rejects_non_plain_data(value: object) -> None:
    codec = JSONCodec()
    with pytest.raises(CodecEncodeError):
        codec.encode(value)


def test_json_codec_decode_rejects_non_utf8_bytes() -> None:
    codec = JSONCodec()
    with pytest.raises(CodecDecodeError):
        codec.decode(b"\xff")


def test_json_codec_decode_rejects_invalid_json() -> None:
    codec = JSONCodec()
    with pytest.raises(CodecDecodeError):
        codec.decode(b"{invalid-json}")

