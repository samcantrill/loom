"""Contract tests for codec protocol implementations."""

import importlib
from collections.abc import Mapping
from types import ModuleType

import pytest

from loom.io.codecs import Codec, CodecRegistry
from loom.plugins import (
    LOOM_CODECS_GROUP,
    PluginRegistrationError,
    PluginRecord,
    load_codec_entry_points,
)


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


class _ContractCodec:
    key = "contract.codec.v1"

    def __init__(self, label: str = "factory") -> None:
        self._label = label

    def encode(self, obj: object, *, metadata: Mapping[str, object] | None = None) -> bytes:
        del metadata
        return f"{self._label}:{obj}".encode("utf-8")

    def decode(self, data: bytes, *, metadata: Mapping[str, object] | None = None) -> str:
        del metadata
        return data.decode("utf-8")


def test_contract_codec_adapter_loads_fake_entry_point_into_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = CodecRegistry()
    record = PluginRecord(
        group=LOOM_CODECS_GROUP,
        name="contract",
        value="loom.plugins.contract_codec_adapter:factory",
    )

    module = ModuleType("loom.plugins.contract_codec_adapter")
    setattr(module, "factory", lambda: _ContractCodec("contract"))
    monkeypatch.setattr(importlib, "import_module", lambda name, package=None: module)

    load_codec_entry_points((record,), registry, strict=True)
    assert registry.decode("contract.codec.v1", registry.encode("contract.codec.v1", "hello")) == "contract:hello"


def test_contract_codec_adapter_rejects_duplicate_runtime_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    duplicate_a = PluginRecord(
        group=LOOM_CODECS_GROUP,
        name="first",
        value="loom.plugins.contract_codec_duplicate:klass",
    )
    duplicate_b = PluginRecord(
        group=LOOM_CODECS_GROUP,
        name="second",
        value="loom.plugins.contract_codec_duplicate:factory",
    )

    module = ModuleType("loom.plugins.contract_codec_duplicate")
    setattr(module, "klass", _ContractCodec)

    def factory() -> _ContractCodec:
        return _ContractCodec("factory")

    setattr(module, "factory", factory)
    monkeypatch.setattr(importlib, "import_module", lambda name, package=None: module)

    result = load_codec_entry_points((duplicate_a, duplicate_b), CodecRegistry(), strict=False)
    assert result.loaded_count == 1
    assert result.failure_count == 1
    assert result.failures[0].operation == "registration"

    with pytest.raises(PluginRegistrationError):
        load_codec_entry_points((duplicate_a, duplicate_b), CodecRegistry(), strict=True)
