"""Codec registry."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from loom.ids import CodecKey

from loom.io.codecs.base import Codec
from loom.io.codecs.bytes_codec import BytesCodec
from loom.io.codecs.errors import CodecEncodeError, CodecError, CodecRegistrationError, CodecDecodeError, UnknownCodecError
from loom.io.codecs.json_codec import JSONCodec
from loom.io.codecs.text_codec import TextCodec
from loom.serialization import PlainData


class CodecRegistry:
    """Mutable, instance-local codec registry."""

    def __init__(self, codecs: Iterable[Codec] = ()) -> None:
        self._codecs: dict[CodecKey, Codec] = {}
        for codec in codecs:
            self.register(codec)

    def register(self, codec: Codec) -> None:
        if not isinstance(codec, Codec):
            raise CodecRegistrationError(f"Invalid codec object: {type(codec)!r}")
        key = codec.key
        if not isinstance(key, str) or not key:
            raise CodecRegistrationError("Codec key must be a non-empty string")
        if not callable(getattr(codec, "encode", None)) or not callable(getattr(codec, "decode", None)):
            raise CodecRegistrationError(f"Codec {key!r} must implement encode and decode callables")
        if key in self._codecs:
            keys = ", ".join(self.keys())
            raise CodecRegistrationError(
                f'Duplicate codec key "{key}". Registered codecs: {keys}.',
            )
        self._codecs[key] = codec

    def get(self, key: str) -> Codec:
        if not isinstance(key, str) or not key:
            keys = ", ".join(self.keys())
            raise UnknownCodecError(
                f"Invalid codec key {key!r}. Registered codecs: {keys}.",
            )
        if key not in self._codecs:
            keys = ", ".join(self.keys())
            raise UnknownCodecError(
                f'No codec registered for key "{key}". Registered codecs: {keys}.',
            )
        return self._codecs[key]

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._codecs.keys()))

    def encode(
        self,
        key: str,
        obj: object,
        *,
        metadata: Mapping[str, PlainData] | None = None,
    ) -> bytes:
        codec = self.get(key)
        try:
            return codec.encode(obj, metadata=metadata)
        except CodecError:
            raise
        except Exception as exc:
            raise CodecEncodeError(f'Codec "{key}" could not encode object: {exc}') from exc

    def decode(
        self,
        key: str,
        data: bytes,
        *,
        metadata: Mapping[str, PlainData] | None = None,
    ) -> object:
        codec = self.get(key)
        try:
            return codec.decode(data, metadata=metadata)
        except CodecError:
            raise
        except Exception as exc:
            raise CodecDecodeError(f'Codec "{key}" could not decode data: {exc}') from exc


def create_default_codec_registry() -> CodecRegistry:
    """Create a registry with JSON, text, and bytes codecs."""

    registry = CodecRegistry()
    registry.register(JSONCodec())
    registry.register(TextCodec())
    registry.register(BytesCodec())
    return registry


__all__ = ["CodecRegistry", "create_default_codec_registry"]
