"""Unit tests for registry-specific plugin adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import ModuleType
from typing import cast

import importlib
import pytest

from weave.recipes import RecipeCatalog
from loom.io.codecs import CodecRegistry
from loom.pipeline.event_sinks import (
    EventObserverLinkRecord,
    EventSinkContext,
    EventSinkRegistration,
    EventSinkRegistry,
    EventSinkSubscription,
)
from loom.pipeline.events import EventReference, PipelineEventRecord
from loom.pipeline.executors import (
    ExecutorFactory,
    ExecutorRegistration,
    ExecutorRegistry,
)
from loom.pipeline.resources import ResourceEntry, ResourceValidatorRegistry
from loom.pipeline.runtime import ExecutorDescriptor
from loom.plugins import (
    LOOM_CODECS_GROUP,
    LOOM_EVENT_SINKS_GROUP,
    LOOM_EXECUTORS_GROUP,
    LOOM_RECIPES_GROUP,
    LOOM_RESOURCE_VALIDATORS_GROUP,
    PluginDuplicateError,
    PluginLoadError,
    PluginRecord,
    PluginRegistrationError,
    load_codec_entry_points,
    load_event_sink_entry_points,
    load_executor_entry_points,
    load_recipe_entry_points,
    load_resource_validator_entry_points,
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

    def encode(
        self, obj: object, *, metadata: Mapping[str, object] | None = None
    ) -> bytes:
        del metadata
        return f"{self._label}:{obj}".encode("utf-8")

    def decode(
        self, data: bytes, *, metadata: Mapping[str, object] | None = None
    ) -> str:
        del metadata
        return data.decode("utf-8")


class _InstanceCodec(_ClassCodec):
    key = "instance.v1"


class _FactoryCodec(_ClassCodec):
    key = "factory.v1"


def _instance_codec_factory() -> _FactoryCodec:
    return _FactoryCodec("factory")


def _executor_registration(name: str) -> ExecutorRegistration:
    return ExecutorRegistration(
        descriptor=ExecutorDescriptor(name=name),
        factory=cast(ExecutorFactory, lambda **_: object()),
    )


def test_load_executor_entry_points_accepts_registration_and_no_arg_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    direct = _executor_registration("direct")
    factory = _executor_registration("factory")
    records = (
        PluginRecord(
            group=LOOM_EXECUTORS_GROUP,
            name="direct",
            value="loom.plugins._executor_direct:registration",
        ),
        PluginRecord(
            group=LOOM_EXECUTORS_GROUP,
            name="factory",
            value="loom.plugins._executor_factory:registration_factory",
        ),
    )
    modules = {
        "loom.plugins._executor_direct": _module_with_attrs(
            "loom.plugins._executor_direct", {"registration": direct}
        ),
        "loom.plugins._executor_factory": _module_with_attrs(
            "loom.plugins._executor_factory",
            {"registration_factory": lambda: factory},
        ),
    }

    def import_module(name: str, package: str | None = None) -> ModuleType:
        del package
        return modules[name]

    monkeypatch.setattr(importlib, "import_module", import_module)
    registry = ExecutorRegistry()

    result = load_executor_entry_points(
        records, registry, selected=records, strict=True
    )

    assert result.loaded_count == 2
    assert registry.names == ("direct", "factory")
    assert registry.resolve("direct") is direct
    assert registry.resolve("factory") is factory


def test_load_executor_entry_points_rejects_entry_point_descriptor_name_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = PluginRecord(
        group=LOOM_EXECUTORS_GROUP,
        name="declared",
        value="loom.plugins._executor_mismatch:registration",
    )
    module = _module_with_attrs(
        "loom.plugins._executor_mismatch",
        {"registration": _executor_registration("different")},
    )

    def import_module(name: str, package: str | None = None) -> ModuleType:
        del name, package
        return module

    monkeypatch.setattr(importlib, "import_module", import_module)
    registry = ExecutorRegistry()

    with pytest.raises(PluginRegistrationError, match="registration failed"):
        load_executor_entry_points((record,), registry, strict=True)
    assert registry.names == ()


def test_load_resource_validator_entry_points_registers_direct_callable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[ResourceEntry, str]] = []

    def validate(entry: ResourceEntry, path: str) -> None:
        calls.append((entry, path))

    record = PluginRecord(
        group=LOOM_RESOURCE_VALIDATORS_GROUP,
        name="project.device",
        value="loom.plugins._resource_validator:validate",
    )
    module = _module_with_attrs(
        "loom.plugins._resource_validator", {"validate": validate}
    )

    def import_module(name: str, package: str | None = None) -> ModuleType:
        del name, package
        return module

    monkeypatch.setattr(importlib, "import_module", import_module)

    registry, result = load_resource_validator_entry_points(
        (record,), ResourceValidatorRegistry(), selected=(record,), strict=True
    )
    entry = ResourceEntry(kind="project.device", amount=1)
    registry.validate(entry, path="resources.entries['project.device']")

    assert result.loaded_count == 1
    assert calls == [(entry, "resources.entries['project.device']")]


@dataclass(slots=True)
class _SinkContext:
    run_uri: str
    event_reference: EventReference
    links: list[EventObserverLinkRecord] = field(default_factory=list)

    def record_event_observer_link(self, link: EventObserverLinkRecord) -> None:
        self.links.append(link)


def _event_reference() -> EventReference:
    return EventReference(
        event_id="event-1",
        run_uri="run://event-sink-plugin-test",
        event_type="run.started",
        occurred_at="2020-01-01T00:00:00Z",
        durability="durable",
        sequence=1,
    )


def test_load_recipe_entry_points_registers_selected_names_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_load_recipe_entry_points_keeps_strict_default_replace_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            return _module_with_attrs(
                name, {"recipe": lambda value: {"value": f"replacement:{value}"}}
            )
        raise AssertionError(f"unexpected import {name}")

    monkeypatch.setattr(importlib, "import_module", import_module)

    best_effort = load_recipe_entry_points((duplicate_name,), catalog, strict=False)
    assert best_effort.loaded_count == 0
    assert best_effort.failure_count == 1
    assert best_effort.failures[0].operation == "registration"

    with pytest.raises(PluginRegistrationError):
        load_recipe_entry_points((duplicate_name,), catalog, strict=True)

    replaced = load_recipe_entry_points(
        (duplicate_name,), catalog, strict=True, replace=True
    )
    assert replaced.loaded_count == 1
    assert catalog.get("dup")("test") == {"value": "replacement:test"}
    assert isinstance(replaced.failures, tuple)


def test_load_recipe_entry_points_rejects_invalid_registration_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_load_codec_entry_points_supports_instance_class_and_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = CodecRegistry()
    instance = _InstanceCodec("instance")

    records = (
        PluginRecord(
            group=LOOM_CODECS_GROUP,
            name="instance",
            value="loom.plugins._codec_instance:codec",
        ),
        PluginRecord(
            group=LOOM_CODECS_GROUP,
            name="class",
            value="loom.plugins._codec_class:klass",
        ),
        PluginRecord(
            group=LOOM_CODECS_GROUP,
            name="factory",
            value="loom.plugins._codec_factory:factory",
        ),
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


def test_load_codec_entry_points_wraps_constructor_and_factory_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NeedsArg:
        key = "constructor.v1"

        def __init__(self, _required: str) -> None:
            self._required = _required

        def encode(
            self, obj: object, *, metadata: Mapping[str, object] | None = None
        ) -> bytes:
            del metadata
            return str(obj).encode("utf-8")

        def decode(
            self, data: bytes, *, metadata: Mapping[str, object] | None = None
        ) -> str:
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


def test_load_codec_entry_points_rejects_duplicate_runtime_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_load_event_sink_entry_points_supports_callable_class_and_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = EventSinkRegistry()
    calls: list[str] = []

    def function_sink(
        event: PipelineEventRecord | EventReference,
        context: EventSinkContext,
    ) -> None:
        del event, context
        calls.append("function")

    class _ClassSink:
        def __call__(
            self,
            event: PipelineEventRecord | EventReference,
            context: EventSinkContext,
        ) -> None:
            del event, context
            calls.append("class")

    def sink_factory() -> object:
        def factory_sink(
            event: PipelineEventRecord | EventReference,
            context: EventSinkContext,
        ) -> None:
            del event, context
            calls.append("factory")

        return factory_sink

    records = (
        PluginRecord(
            group=LOOM_EVENT_SINKS_GROUP,
            name="function",
            value="loom.plugins._event_sink_function:sink",
        ),
        PluginRecord(
            group=LOOM_EVENT_SINKS_GROUP,
            name="class",
            value="loom.plugins._event_sink_class:sink",
        ),
        PluginRecord(
            group=LOOM_EVENT_SINKS_GROUP,
            name="factory",
            value="loom.plugins._event_sink_factory:sink",
        ),
    )
    modules = {
        "loom.plugins._event_sink_function": _module_with_attrs(
            "loom.plugins._event_sink_function",
            {"sink": function_sink},
        ),
        "loom.plugins._event_sink_class": _module_with_attrs(
            "loom.plugins._event_sink_class",
            {"sink": _ClassSink},
        ),
        "loom.plugins._event_sink_factory": _module_with_attrs(
            "loom.plugins._event_sink_factory",
            {"sink": sink_factory},
        ),
    }

    def import_module(name: str, package: str | None = None) -> ModuleType:
        del package
        return modules[name]

    monkeypatch.setattr(importlib, "import_module", import_module)

    result = load_event_sink_entry_points(
        records,
        registry,
        selected=records,
        strict=True,
    )

    event_reference = _event_reference()
    dispatch = registry.dispatch(
        event_reference,
        _SinkContext(run_uri=event_reference.run_uri, event_reference=event_reference),
    )

    assert result.loaded_count == 3
    assert registry.names() == ("class", "factory", "function")
    assert dispatch.succeeded is True
    assert calls == ["class", "factory", "function"]


def test_load_event_sink_entry_points_accepts_filtered_registration_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = EventSinkRegistry()
    calls: list[str] = []

    def registration_factory() -> EventSinkRegistration:
        return EventSinkRegistration(
            sink=lambda event, _context: calls.append(event.event_type),
            subscription=EventSinkSubscription(event_types=("run.completed",)),
        )

    record = PluginRecord(
        group=LOOM_EVENT_SINKS_GROUP,
        name="completed",
        value="loom.plugins._filtered_event_sink:registration_factory",
    )
    module = _module_with_attrs(
        "loom.plugins._filtered_event_sink",
        {"registration_factory": registration_factory},
    )
    monkeypatch.setattr(importlib, "import_module", lambda *_args: module)

    load_event_sink_entry_points((record,), registry, selected=(record,), strict=True)
    reference = _event_reference()
    registry.dispatch(
        reference,
        _SinkContext(run_uri=reference.run_uri, event_reference=reference),
    )

    assert calls == []
    assert registry.registration_items()[0][1].subscription == EventSinkSubscription(
        event_types=("run.completed",)
    )


def test_load_event_sink_entry_points_reports_invalid_shapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = EventSinkRegistry()

    class _NeedsArg:
        def __init__(self, required: str) -> None:
            self.required = required

        def __call__(
            self,
            event: PipelineEventRecord | EventReference,
            context: EventSinkContext,
        ) -> None:
            del event, context

    def invalid_factory() -> object:
        return object()

    constructor_record = PluginRecord(
        group=LOOM_EVENT_SINKS_GROUP,
        name="constructor",
        value="loom.plugins._event_sink_constructor:sink",
    )
    factory_record = PluginRecord(
        group=LOOM_EVENT_SINKS_GROUP,
        name="factory",
        value="loom.plugins._event_sink_factory:sink",
    )
    invalid_name_record = PluginRecord(
        group=LOOM_EVENT_SINKS_GROUP,
        name="BadName",
        value="loom.plugins._event_sink_function:sink",
    )

    def valid_sink(
        event: PipelineEventRecord | EventReference,
        context: EventSinkContext,
    ) -> None:
        del event, context

    modules = {
        "loom.plugins._event_sink_constructor": _module_with_attrs(
            "loom.plugins._event_sink_constructor",
            {"sink": _NeedsArg},
        ),
        "loom.plugins._event_sink_factory": _module_with_attrs(
            "loom.plugins._event_sink_factory",
            {"sink": invalid_factory},
        ),
        "loom.plugins._event_sink_function": _module_with_attrs(
            "loom.plugins._event_sink_function",
            {"sink": valid_sink},
        ),
    }

    def import_module(name: str, package: str | None = None) -> ModuleType:
        del package
        return modules[name]

    monkeypatch.setattr(importlib, "import_module", import_module)

    best_effort = load_event_sink_entry_points(
        records=(constructor_record, factory_record, invalid_name_record),
        registry=registry,
        selected=(constructor_record, factory_record, invalid_name_record),
        strict=False,
    )

    assert best_effort.loaded_count == 0
    assert best_effort.failure_count == 3
    assert [failure.operation for failure in best_effort.failures] == [
        "registration",
        "registration",
        "registration",
    ]

    with pytest.raises(PluginRegistrationError):
        load_event_sink_entry_points(
            records=(constructor_record, factory_record),
            registry=EventSinkRegistry(),
            selected=(constructor_record, factory_record),
            strict=True,
        )
