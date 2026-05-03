"""JSON codec for plain structured data."""

from __future__ import annotations

from collections.abc import Mapping

from loom.serialization import DeserializationError, PlainData, PlainDataError
from loom.serialization.json import json_dumps_pretty, json_loads
from loom.serialization.plain import ensure_plain_data

from loom.io.codecs.errors import CodecDecodeError, CodecEncodeError


class JSONCodec:
    """Codec for deterministic, pretty-printed JSON bytes."""

    key = "json.v1"

    def encode(self, obj: object, *, metadata: Mapping[str, PlainData] | None = None) -> bytes:
        if metadata is not None:
            ensure_plain_data(metadata, path="$")
        try:
            plain = ensure_plain_data(obj, path="$")
            return json_dumps_pretty(plain, sort_keys=True).encode("utf-8")
        except PlainDataError as exc:
            raise CodecEncodeError(f'Codec "{self.key}" could not encode object: {exc}') from exc
        except (TypeError, ValueError) as exc:
            raise CodecEncodeError(f'Codec "{self.key}" encoding failed: {exc}') from exc
        except Exception as exc:
            raise CodecEncodeError(f'Codec "{self.key}" encoding failed') from exc

    def decode(self, data: bytes, *, metadata: Mapping[str, PlainData] | None = None) -> object:
        if metadata is not None:
            ensure_plain_data(metadata, path="$")
        try:
            if not isinstance(data, (bytes, bytearray, memoryview)):
                raise TypeError("expected bytes")
            return json_loads(bytes(data).decode("utf-8"), path="$")
        except DeserializationError as exc:
            raise CodecDecodeError(f'Codec "{self.key}" could not decode JSON text: {exc}') from exc
        except (UnicodeDecodeError, ValueError) as exc:
            raise CodecDecodeError(f'Codec "{self.key}" could not decode data: {exc}') from exc
        except Exception as exc:
            raise CodecDecodeError(f'Codec "{self.key}" decoding failed') from exc


__all__ = ["JSONCodec"]
