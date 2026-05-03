"""Contract tests for codec protocol implementations."""

from collections.abc import Mapping

from loom.io.codecs import Codec, CodecRegistry


class DummyCodec:
    """Downstream-style codec with protocol shape."""

    key = "downstream.v1"

    def encode(self, obj: object, *, metadata: Mapping[str, object] | None = None) -> bytes:
        del metadata
        return f"{obj}".encode("utf-8")

    def decode(self, data: bytes, *, metadata: Mapping[str, object] | None = None) -> str:
        del metadata
        return data.decode("utf-8")


def test_downstream_codec_satisfies_protocol_and_registry() -> None:
    codec = DummyCodec()
    assert isinstance(codec, Codec)
    registry = CodecRegistry()
    registry.register(codec)
    encoded = registry.encode("downstream.v1", "value")
    assert registry.decode("downstream.v1", encoded) == "value"


def test_builtin_codecs_satisfy_codec_protocol() -> None:
    from loom.io.codecs import JSONCodec, TextCodec, BytesCodec

    assert isinstance(JSONCodec(), Codec)
    assert isinstance(TextCodec(), Codec)
    assert isinstance(BytesCodec(), Codec)
