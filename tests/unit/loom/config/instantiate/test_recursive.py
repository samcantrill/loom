"""Unit tests for recursive target instantiation."""

from functools import partial

import pytest

from loom.config.errors import ReservedConfigKeyError, TargetInstantiationError
from loom.config.instantiate import instantiate
from tests.support.config_samples import AddService, EchoService, concat


def test_instantiate_scalar_passthrough() -> None:
    assert instantiate("value") == "value"


def test_instantiate_nested_mappings_and_lists() -> None:
    value = {
        "root": {"_target_": "tests.support.config_samples:EchoService", "value": "x"},
        "items": [
            {"_target_": "tests.support.config_samples:concat", "prefix": "a", "suffix": "b"},
            "leaf",
        ],
    }
    result = instantiate(value)
    assert isinstance(result, dict)
    assert isinstance(result["root"], EchoService)
    assert result["root"].value == "x"
    assert result["items"][0] == "ab"
    assert result["items"][1] == "leaf"


def test_instantiate_positional_args() -> None:
    result = instantiate(
        {"_target_": "tests.support.config_samples:AddService", "_args_": [1, 2], "_partial_": False}
    )
    assert isinstance(result, AddService)
    assert result.left == 1
    assert result.right == 2


def test_instantiate_partial_mode() -> None:
    partial_call = instantiate({"_target_": "tests.support.config_samples.concat", "_args_": ["a"], "_partial_": True})
    assert isinstance(partial_call, partial)
    assert partial_call.args == ("a",)
    assert partial_call.keywords == {}


def test_instantiate_reserved_key_misuse() -> None:
    with pytest.raises(ReservedConfigKeyError):
        instantiate({"_target_": "tests.support.config_samples:concat", "_recipe_": "bad"})
    with pytest.raises(ReservedConfigKeyError):
        instantiate({"value": {"_args_": [1]}})
    with pytest.raises(ReservedConfigKeyError):
        instantiate({"value": {"_partial_": True}})
    with pytest.raises(ReservedConfigKeyError):
        instantiate({"value": {"_inject_": {"x": "y"}}})


def test_instantiate_rejects_non_callable_target() -> None:
    with pytest.raises(TargetInstantiationError):
        instantiate({"_target_": "tests.support.config_samples:NON_CALLABLE_TARGET"})


def test_instantiate_constructor_failure_wraps() -> None:
    with pytest.raises(TargetInstantiationError) as exc:
        instantiate({"_target_": "tests.support.config_samples:Concat", "_args_": ["left", "middle", "right"]})
    assert exc.value.__cause__ is not None
