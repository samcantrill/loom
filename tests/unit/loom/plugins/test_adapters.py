"""Unit tests for registry-specific plugin adapters."""

from __future__ import annotations

from collections.abc import Mapping
from types import ModuleType

import importlib
import pytest

from loom.config.recipes import RecipeCatalog
from loom.io.codecs import CodecRegistry
from loom.plugins import (
    LOOM_CODECS_GROUP,
    LOOM_RECIPES_GROUP,
    PluginDuplicateError,
    PluginLoadError,
    PluginRecord,
    PluginRegistrationError,
    load_codec_entry_points,
    load_recipe_entry_points,
)


def _module_with_attrs(name: str, attrs: Mapping[str, object]) -> ModuleType:
    module = ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


class _RecipeFunction:
    def __call__(self, value: str) -> dict[str, str]:
        return {"value": value}


class _ClassCodec:
    key = "class.v1"

    def __init__(self, label: str | None = None) -> None:
        self._label = "class" if label is None else label

    def encode(self, obj: object, *, metadata: Mapping[str, object] | None = None) -> bytes:
        del metadata
        return f"{self._label}:{obj}".encode("utf-8")

    def decode(self, data: bytes, *, metadata: Mapping[str, object] | None = None) -> str:
        del metadata
        return data.decode("utf-8")


class _InstanceCodec(_ClassCodec):
    key = "instance.v1"


class _FactoryCodec(_ClassCodec):
    key = "factory.v1"


def _instance_codec_factory() -> _FactoryCodec:
    return _FactoryCodec("factory")


def test_load_recipe_entry_points_registers_selected_names_only(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = RecipeCatalog()
    selected = PluginRecord(
        group=LOOM_RECIPES_GROUP,
        name="selected",
        value="loom.plugins._recipe_selected:recipe",
    )
    skipped = PluginRecord(
        group=LOOM_RECIPES_GROUP,
        name="skipped",
        value="loom.plugins._recipe_skipped:recipe",
    )

    recipe = _RecipeFunction()
    imported: list[str] = []

    def import_module(name: str, package: str | None = None) -> ModuleType:
        imported.append(name)
        if name == "loom.plugins._recipe_selected":
            return _module_with_attrs(name, {"recipe": recipe})
        return _module_with_attrs(name, {"recipe": _RecipeFunction()})

    monkeypatch.setattr(importlib, "import_module", import_module)

    result = load_recipe_entry_points(
        records=(selected, skipped),
        catalog=catalog,
        selected=(selected,),
        strict=True,
    )

    assert result.loaded_count == 1
    assert result.loaded[0].record.name == "selected"
    assert catalog.get("selected") is recipe
    assert imported == ["loom.plugins._recipe_selected"]


def test_load_recipe_entry_points_keeps_strict_default_replace_false(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = RecipeCatalog()
    catalog.register("dup", lambda value: {"value": value}, replace=False)

    duplicate_name = PluginRecord(
        group=LOOM_RECIPES_GROUP,
        name="dup",
        value="loom.plugins._recipe_duplicate:recipe",
    )

    def import_module(name: str, package: str | None = None) -> ModuleType:
        del package
        if name == "loom.plugins._recipe_duplicate":
            return _module_with_attrs(name, {"recipe": lambda value: {"value": f"replacement:{value}"}})
        raise AssertionError(f"unexpected import {name}")

    monkeypatch.setattr(importlib, "import_module", import_module)

    best_effort = load_recipe_entry_points((duplicate_name,), catalog, strict=False)
    assert best_effort.loaded_count == 0
    assert best_effort.failure_count == 1
    assert best_effort.failures[0].operation == "registration"

    with pytest.raises(PluginRegistrationError):
        load_recipe_entry_points((duplicate_name,), catalog, strict=True)

    replaced = load_recipe_entry_points((duplicate_name,), catalog, strict=True, replace=True)
    assert replaced.loaded_count == 1
    assert catalog.get("dup")("test") == {"value": "replacement:test"}
    assert isinstance(replaced.failures, tuple)


def test_load_recipe_entry_points_rejects_invalid_registration_target(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = RecipeCatalog()
    invalid_record = PluginRecord(
        group=LOOM_RECIPES_GROUP,
        name="invalid",
        value="loom.plugins._invalid_recipe:thing",
    )

    def import_module(name: str, package: str | None = None) -> ModuleType:
        del package
        assert name == "loom.plugins._invalid_recipe"
        return _module_with_attrs(name, {"thing": object()})

    monkeypatch.setattr(importlib, "import_module", import_module)

    best_effort = load_recipe_entry_points((invalid_record,), catalog, strict=False)
    assert best_effort.loaded_count == 0
    assert best_effort.failures[0].operation == "registration"

    with pytest.raises(PluginLoadError):
        load_recipe_entry_points((invalid_record,), catalog, strict=True)


def test_load_recipe_entry_points_fail_closed_on_selected_duplicate_names() -> None:
    selected_a = PluginRecord(
        group=LOOM_RECIPES_GROUP,
        name="dup",
        value="loom.plugins._recipe_duplicate_a:recipe",
    )
    selected_b = PluginRecord(
        group=LOOM_RECIPES_GROUP,
        name="dup",
        value="loom.plugins._recipe_duplicate_b:recipe",
    )

    with pytest.raises(PluginDuplicateError) as exc_info:
        load_recipe_entry_points((selected_a, selected_b), RecipeCatalog(), strict=True)

    result = exc_info.value.result
    assert result is not None
    assert result.duplicate_count == 1
    assert result.failure_count == 0
    assert result.loaded_count == 0


def test_load_codec_entry_points_supports_instance_class_and_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = CodecRegistry()
    instance = _InstanceCodec("instance")

    records = (
        PluginRecord(group=LOOM_CODECS_GROUP, name="instance", value="loom.plugins._codec_instance:codec"),
        PluginRecord(group=LOOM_CODECS_GROUP, name="class", value="loom.plugins._codec_class:klass"),
        PluginRecord(group=LOOM_CODECS_GROUP, name="factory", value="loom.plugins._codec_factory:factory"),
    )

    modules = {
        "loom.plugins._codec_instance": _module_with_attrs(
            "loom.plugins._codec_instance",
            {"codec": instance},
        ),
        "loom.plugins._codec_class": _module_with_attrs(
            "loom.plugins._codec_class",
            {"klass": _ClassCodec},
        ),
        "loom.plugins._codec_factory": _module_with_attrs(
            "loom.plugins._codec_factory",
            {"factory": _instance_codec_factory},
        ),
    }

    def import_module(name: str, package: str | None = None) -> ModuleType:
        del package
        return modules[name]

    monkeypatch.setattr(importlib, "import_module", import_module)

    result = load_codec_entry_points(records, registry, selected=records, strict=True)

    assert result.loaded_count == 3
    assert registry.get("instance.v1") is instance
    assert isinstance(registry.get("class.v1"), _ClassCodec)
    assert registry.get("factory.v1").key == "factory.v1"
    assert registry.encode("factory.v1", "hello") == b"factory:hello"


def test_load_codec_entry_points_wraps_constructor_and_factory_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    class _NeedsArg:
        key = "constructor.v1"

        def __init__(self, _required: str) -> None:
            self._required = _required

        def encode(self, obj: object, *, metadata: Mapping[str, object] | None = None) -> bytes:
            del metadata
            return str(obj).encode("utf-8")

        def decode(self, data: bytes, *, metadata: Mapping[str, object] | None = None) -> str:
            del metadata
            return data.decode("utf-8")

    def broken_factory() -> _ClassCodec:
        raise RuntimeError("factory failed")

    constructor_record = PluginRecord(
        group=LOOM_CODECS_GROUP,
        name="constructor",
        value="loom.plugins._codec_constructor:klass",
    )
    factory_record = PluginRecord(
        group=LOOM_CODECS_GROUP,
        name="factory",
        value="loom.plugins._codec_factory:factory",
    )

    def import_module(name: str, package: str | None = None) -> ModuleType:
        del package
        if name == "loom.plugins._codec_constructor":
            return _module_with_attrs(name, {"klass": _NeedsArg})
        return _module_with_attrs(name, {"factory": broken_factory})

    monkeypatch.setattr(importlib, "import_module", import_module)

    best_effort = load_codec_entry_points(
        records=(constructor_record, factory_record),
        registry=CodecRegistry(),
        selected=(constructor_record, factory_record),
        strict=False,
    )

    assert best_effort.loaded_count == 0
    assert best_effort.failure_count == 2
    assert best_effort.failures[0].operation == "registration"
    assert best_effort.failures[1].operation == "registration"

    with pytest.raises(PluginRegistrationError):
        load_codec_entry_points(
            records=(constructor_record, factory_record),
            registry=CodecRegistry(),
            selected=(constructor_record, factory_record),
            strict=True,
        )


def test_load_codec_entry_points_rejects_duplicate_runtime_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    duplicate_record_a = PluginRecord(
        group=LOOM_CODECS_GROUP,
        name="first",
        value="loom.plugins._codec_duplicate:klass",
    )
    duplicate_record_b = PluginRecord(
        group=LOOM_CODECS_GROUP,
        name="second",
        value="loom.plugins._codec_duplicate:factory",
    )

    class _DuplicateCodec(_ClassCodec):
        key = "shared.v1"

    def duplicate_factory() -> _DuplicateCodec:
        return _DuplicateCodec("factory")

    module = _module_with_attrs(
        "loom.plugins._codec_duplicate",
        {"klass": _DuplicateCodec, "factory": duplicate_factory},
    )

    def import_module(name: str, package: str | None = None) -> ModuleType:
        del package
        return module

    monkeypatch.setattr(importlib, "import_module", import_module)

    best_effort = load_codec_entry_points(
        records=(duplicate_record_a, duplicate_record_b),
        registry=CodecRegistry(),
        selected=(duplicate_record_a, duplicate_record_b),
        strict=False,
    )

    assert best_effort.loaded_count == 1
    assert best_effort.failure_count == 1
    failure = best_effort.failures[0]
    assert failure.operation == "registration"
    assert "Duplicate codec key" in failure.message

    with pytest.raises(PluginRegistrationError):
        load_codec_entry_points(
            records=(duplicate_record_a, duplicate_record_b),
            registry=CodecRegistry(),
            selected=(duplicate_record_a, duplicate_record_b),
            strict=True,
        )
