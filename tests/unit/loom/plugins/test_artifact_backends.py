"""Unit tests for artifact-store backend plugin adapter."""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from types import ModuleType

import pytest

from loom.artifacts import ArtifactStoreRef, ImmutableArtifactLookupRequest
from loom.pipeline.stores import (
    ArtifactStoreBackendDescriptor,
    ArtifactStoreBackendDiagnostic,
    ArtifactStoreBackendHandler,
    ArtifactStoreBackendOperation,
    ArtifactStoreBackendOperationResult,
    ArtifactStoreBackendRegistry,
    ArtifactStoreCapabilities,
    ArtifactStoreCapabilityRecord,
    ArtifactStoreCapabilitySupport,
)
from loom.plugins import (
    LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
    LOOM_CODECS_GROUP,
    PluginRecord,
    PluginRegistrationError,
    load_artifact_store_backend_entry_points,
)
from loom.serialization import PlainData


pytestmark = pytest.mark.unit


class _FakeHandler:
    def __init__(
        self,
        descriptor: ArtifactStoreBackendDescriptor,
        store_ref: ArtifactStoreRef,
        capabilities: ArtifactStoreCapabilities,
    ) -> None:
        self._descriptor = descriptor
        self._store_ref = store_ref
        self._capabilities = capabilities

    @property
    def descriptor(self) -> ArtifactStoreBackendDescriptor:
        return self._descriptor

    @property
    def store_ref(self) -> ArtifactStoreRef:
        return self._store_ref

    @property
    def capabilities(self) -> ArtifactStoreCapabilities:
        return self._capabilities

    def validate_store_ref(
        self,
        store_ref: ArtifactStoreRef,
    ) -> tuple[ArtifactStoreBackendDiagnostic, ...]:
        del store_ref
        return ()

    def redact_store_ref(self, store_ref: ArtifactStoreRef) -> ArtifactStoreRef:
        return store_ref

    def check(self) -> tuple[ArtifactStoreBackendDiagnostic, ...]:
        return ()

    def lookup(
        self,
        request: ImmutableArtifactLookupRequest,
    ) -> ArtifactStoreBackendOperationResult:
        del request
        return ArtifactStoreBackendOperationResult.unknown(
            ArtifactStoreBackendOperation.LOOKUP
        )

    def unsupported_operation(
        self,
        operation: ArtifactStoreBackendOperation | str,
        *,
        message: str | None = None,
        detail: Mapping[str, PlainData] | None = None,
    ) -> ArtifactStoreBackendOperationResult:
        return ArtifactStoreBackendOperationResult.unsupported(
            operation,
            message=message,
            detail=detail,
        )


class _FakeFactory:
    def __init__(self, kind: str) -> None:
        self._kind = kind

    @property
    def descriptor(self) -> ArtifactStoreBackendDescriptor:
        return ArtifactStoreBackendDescriptor(
            kind=self._kind,
            display_name=f"{self._kind} fixture",
            supported_uri_schemes=("fake",),
        )

    def validate_config(
        self,
        config: Mapping[str, PlainData] | None = None,
    ) -> tuple[ArtifactStoreBackendDiagnostic, ...]:
        del config
        return ()

    def redact_config(
        self,
        config: Mapping[str, PlainData] | None = None,
    ) -> Mapping[str, PlainData]:
        return dict(config or {})

    def capabilities(
        self,
        config: Mapping[str, PlainData] | None = None,
    ) -> ArtifactStoreCapabilities:
        del config
        return ArtifactStoreCapabilities(
            backend_kind=self.descriptor.kind,
            records=(
                ArtifactStoreCapabilityRecord(
                    ArtifactStoreBackendOperation.READ,
                    ArtifactStoreCapabilitySupport.SUPPORTED,
                ),
            ),
        )

    def create_handler(
        self,
        store_ref: ArtifactStoreRef,
        *,
        config: Mapping[str, PlainData] | None = None,
        run_context: Mapping[str, PlainData] | None = None,
    ) -> ArtifactStoreBackendHandler:
        del config, run_context
        return _FakeHandler(self.descriptor, store_ref, self.capabilities())


class _FactoryClass(_FakeFactory):
    def __init__(self) -> None:
        super().__init__("class_backend")


def _module_with_attrs(name: str, attrs: Mapping[str, object]) -> ModuleType:
    module = ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def test_load_artifact_store_backend_entry_points_registers_selected_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = PluginRecord(
        group=LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
        name="selected",
        value="loom.plugins._artifact_selected:factory",
    )
    skipped = PluginRecord(
        group=LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
        name="skipped",
        value="loom.plugins._artifact_skipped:factory",
    )
    unrelated = PluginRecord(
        group=LOOM_CODECS_GROUP,
        name="codec",
        value="loom.plugins._codec:factory",
    )
    imported: list[str] = []

    def import_module(name: str, package: str | None = None) -> ModuleType:
        del package
        imported.append(name)
        if name == "loom.plugins._artifact_selected":
            return _module_with_attrs(name, {"factory": _FakeFactory("object_store")})
        if name == "loom.plugins._artifact_skipped":
            return _module_with_attrs(name, {"factory": _FakeFactory("skipped")})
        raise AssertionError(f"unexpected import {name}")

    monkeypatch.setattr(importlib, "import_module", import_module)

    registry = ArtifactStoreBackendRegistry()
    result = load_artifact_store_backend_entry_points(
        records=(selected, skipped, unrelated),
        registry=registry,
        selected=(selected,),
        strict=True,
    )

    assert result.loaded_count == 1
    assert result.loaded[0].record.name == "selected"
    assert registry.registered_kinds == ("object-store",)
    assert imported == ["loom.plugins._artifact_selected"]


def test_load_artifact_store_backend_entry_points_supports_descriptor_and_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    descriptor_factory = _FakeFactory("descriptor_backend")
    descriptor = ArtifactStoreBackendDescriptor(
        kind="descriptor_backend",
        display_name="Descriptor fixture",
        factory=descriptor_factory,
    )
    descriptor_record = PluginRecord(
        group=LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
        name="descriptor",
        value="loom.plugins._artifact_descriptor:descriptor",
    )
    class_record = PluginRecord(
        group=LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
        name="class",
        value="loom.plugins._artifact_class:factory_class",
    )

    modules = {
        "loom.plugins._artifact_descriptor": _module_with_attrs(
            "loom.plugins._artifact_descriptor",
            {"descriptor": descriptor},
        ),
        "loom.plugins._artifact_class": _module_with_attrs(
            "loom.plugins._artifact_class",
            {"factory_class": _FactoryClass},
        ),
    }

    def import_module(name: str, package: str | None = None) -> ModuleType:
        del package
        return modules[name]

    monkeypatch.setattr(importlib, "import_module", import_module)

    registry = ArtifactStoreBackendRegistry()
    result = load_artifact_store_backend_entry_points(
        (descriptor_record, class_record),
        registry,
        strict=True,
    )

    assert result.loaded_count == 2
    assert registry.registered_kinds == ("class-backend", "descriptor-backend")


def test_load_artifact_store_backend_entry_points_reports_registration_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_record = PluginRecord(
        group=LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
        name="invalid",
        value="loom.plugins._artifact_invalid:value",
    )

    def import_module(name: str, package: str | None = None) -> ModuleType:
        del package
        return _module_with_attrs(name, {"value": object()})

    monkeypatch.setattr(importlib, "import_module", import_module)

    registry = ArtifactStoreBackendRegistry()
    best_effort = load_artifact_store_backend_entry_points(
        (invalid_record,),
        registry,
        strict=False,
    )

    assert best_effort.loaded_count == 0
    assert best_effort.failure_count == 1
    assert best_effort.failures[0].operation == "registration"

    with pytest.raises(PluginRegistrationError):
        load_artifact_store_backend_entry_points(
            (invalid_record,),
            ArtifactStoreBackendRegistry(),
            strict=True,
        )


def test_load_artifact_store_backend_entry_points_rejects_duplicate_runtime_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = PluginRecord(
        group=LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
        name="first",
        value="loom.plugins._artifact_duplicate:first",
    )
    second = PluginRecord(
        group=LOOM_ARTIFACT_STORE_BACKENDS_GROUP,
        name="second",
        value="loom.plugins._artifact_duplicate:second",
    )
    module = _module_with_attrs(
        "loom.plugins._artifact_duplicate",
        {
            "first": _FakeFactory("shared_backend"),
            "second": _FakeFactory("shared_backend"),
        },
    )

    def import_module(name: str, package: str | None = None) -> ModuleType:
        del package
        assert name == "loom.plugins._artifact_duplicate"
        return module

    monkeypatch.setattr(importlib, "import_module", import_module)

    best_effort = load_artifact_store_backend_entry_points(
        (first, second),
        ArtifactStoreBackendRegistry(),
        strict=False,
    )
    assert best_effort.loaded_count == 1
    assert best_effort.failure_count == 1
    assert best_effort.failures[0].operation == "registration"
    assert "already registered" in best_effort.failures[0].message

    with pytest.raises(PluginRegistrationError):
        load_artifact_store_backend_entry_points(
            (first, second),
            ArtifactStoreBackendRegistry(),
            strict=True,
        )
