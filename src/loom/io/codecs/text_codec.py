"""UTF-8 text codec."""

from __future__ import annotations

from collections.abc import Mapping

from loom.io.codecs.errors import CodecDecodeError, CodecEncodeError

from loom.io.codecs.base import Codec
from loom.serialization.plain import ensure_plain_data

from loom.serialization import PlainData


class TextCodec:
    """Codec for UTF-8 encoded text."""

    key = "text.v1"

    def __init__(self, encoding: str = "utf-8") -> None:
        if not isinstance(encoding, str) or not encoding:
            raise CodecEncodeError("Encoding must be a non-empty string")
        self.encoding = encoding

    def encode(self, obj: object, *, metadata: Mapping[str, PlainData] | None = None) -> bytes:
        if metadata is not None:
            ensure_plain_data(metadata, path="$")
        if not isinstance(obj, str):
            raise CodecEncodeError(f'Codec "{self.key}" can only encode strings, got {type(obj).__name__}')
        try:
            return obj.encode(self.encoding)
        except (LookupError, ValueError) as exc:
            raise CodecEncodeError(f'Codec "{self.key}" could not encode text: {exc}') from exc

    def decode(self, data: bytes, *, metadata: Mapping[str, PlainData] | None = None) -> str:
        if metadata is not None:
            ensure_plain_data(metadata, path="$")
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise CodecDecodeError(f'Codec "{self.key}" can only decode bytes')
        try:
            return bytes(data).decode(self.encoding)
        except UnicodeError as exc:
            raise CodecDecodeError(f'Codec "{self.key}" could not decode bytes as {self.encoding}.') from exc


__all__ = ["TextCodec"]
