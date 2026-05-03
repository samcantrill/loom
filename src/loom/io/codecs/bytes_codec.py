"""Raw bytes codec."""

from __future__ import annotations

from collections.abc import Mapping

from loom.io.codecs.errors import CodecDecodeError, CodecEncodeError
from loom.serialization import PlainData
from loom.serialization.plain import ensure_plain_data


class BytesCodec:
    """Pass-through codec for raw bytes."""

    key = "bytes.v1"

    def encode(self, obj: object, *, metadata: Mapping[str, PlainData] | None = None) -> bytes:
        if metadata is not None:
            ensure_plain_data(metadata, path="$")
        if not isinstance(obj, (bytes, bytearray, memoryview)):
            raise CodecEncodeError(
                f'Codec "{self.key}" can only encode bytes-like data, got {type(obj).__name__}',
            )
        return bytes(obj)

    def decode(
        self,
        data: bytes | bytearray | memoryview,
        *,
        metadata: Mapping[str, PlainData] | None = None,
    ) -> bytes:
        if metadata is not None:
            ensure_plain_data(metadata, path="$")
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise CodecDecodeError(f'Codec "{self.key}" can only decode bytes-like data')
        return bytes(data)


__all__ = ["BytesCodec"]
