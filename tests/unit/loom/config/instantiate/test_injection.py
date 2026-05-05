"""Unit tests for runtime injection behavior."""

import pytest

from loom.config.errors import RuntimeInjectionError
from loom.config.instantiate import instantiate
from tests.support.config_samples import EchoService


def test_injection_maps_runtime_keys() -> None:
    runtime = {"svc": EchoService("service")}
    value = {"_target_": "tests.support.config_samples:EchoService", "_inject_": {"value": "svc"}}
    instance = instantiate(value, runtime=runtime)
    assert isinstance(instance, EchoService)
    assert instance.value is runtime["svc"]


def test_injection_missing_runtime_key_fails() -> None:
    with pytest.raises(RuntimeInjectionError):
        instantiate(
            {"_target_": "tests.support.config_samples:RuntimePlaceholder", "_inject_": {"value": "missing"}},
            runtime={},
        )


def test_injection_rejects_duplicate_keys() -> None:
    with pytest.raises(RuntimeInjectionError):
        instantiate(
            {
                "_target_": "tests.support.config_samples:RuntimePlaceholder",
                "value": "static",
                "_inject_": {"value": "runtime"},
            },
            runtime={"runtime": "svc"},
        )


def test_injection_rejects_non_mapping_runtime() -> None:
    with pytest.raises(RuntimeInjectionError):
        instantiate({"_target_": "tests.support.config_samples:EchoService", "value": "static"}, runtime="not-a-mapping")  # type: ignore[arg-type]


def test_injection_rejects_invalid_inject_shape() -> None:
    with pytest.raises(RuntimeInjectionError):
        instantiate({"_target_": "tests.support.config_samples:EchoService", "_inject_": ["value"]}, runtime={})  # type: ignore[arg-type]


def test_injection_rejects_invalid_inject_key_shape() -> None:
    with pytest.raises(RuntimeInjectionError):
        instantiate(
            {"_target_": "tests.support.config_samples:RuntimePlaceholder", "_inject_": {1: "runtime"}},
            runtime={"runtime": "svc"},  # type: ignore[arg-type]
        )


def test_injection_rejects_invalid_injected_key_shape() -> None:
    with pytest.raises(RuntimeInjectionError):
        instantiate(
            {"_target_": "tests.support.config_samples:RuntimePlaceholder", "_inject_": {"value": ""}},
            runtime={"runtime": "svc"},
        )
