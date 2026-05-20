"""Unit tests for recursive target instantiation."""

from functools import partial

import pytest

from weave.errors import ReservedConfigKeyError, TargetInstantiationError
from weave.instantiate import instantiate
from tests.support.config_samples import (
    AddService,
    EchoService,
    reset_instantiate_probe_state,
    construction_event_log,
    partial_target_calls,
)


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


def test_instantiate_non_string_sequences_as_lists() -> None:
    result = instantiate(
        (
            "leaf",
            {"_target_": "tests.support.config_samples:concat", "_args_": ("a", "b")},
        )
    )

    assert result == ["leaf", "ab"]


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
    context = exc.value.context
    assert context is not None
    assert context.code == "target_instantiation_failed"
    assert context.config_path == "$"
    assert context.directive == "_target_"


def test_instantiate_preserves_bottom_up_order_in_kwargs() -> None:
    reset_instantiate_probe_state()
    instantiate(
        {
            "_target_": "tests.support.config_samples:ConstructionProbeTarget",
            "left": {"_target_": "tests.support.config_samples:log_and_return", "tag": "left", "value": "L"},
            "right": {"_target_": "tests.support.config_samples:log_and_return", "tag": "right", "value": "R"},
        }
    )
    assert construction_event_log == ["left", "right", "parent"]


def test_instantiate_preserves_bottom_up_order_in_args() -> None:
    reset_instantiate_probe_state()
    instantiate(
        {
            "_target_": "tests.support.config_samples:ConstructionProbeTarget",
            "_args_": (
                {"_target_": "tests.support.config_samples:log_and_return", "tag": "tuple-0", "value": "T0"},
                {"_target_": "tests.support.config_samples:log_and_return", "tag": "tuple-1", "value": "T1"},
            ),
        }
    )
    assert construction_event_log == ["tuple-0", "tuple-1", "parent"]


def test_instantiate_preserves_bottom_up_order_for_nested_lists_and_tuples() -> None:
    reset_instantiate_probe_state()
    instantiate(
        {
            "_target_": "tests.support.config_samples:ConstructionProbeTarget",
            "items": [
                {"_target_": "tests.support.config_samples:log_and_return", "tag": "list-0", "value": "L0"},
                {"_target_": "tests.support.config_samples:log_and_return", "tag": "list-1", "value": "L1"},
            ],
            "pairs": (
                {"_target_": "tests.support.config_samples:log_and_return", "tag": "tuple-0", "value": "U0"},
                {"_target_": "tests.support.config_samples:log_and_return", "tag": "tuple-1", "value": "U1"},
            ),
        }
    )
    assert construction_event_log == ["list-0", "list-1", "tuple-0", "tuple-1", "parent"]


def test_instantiate_partial_mode_recursively_constructs_args_kwargs_and_injects_runtime() -> None:
    reset_instantiate_probe_state()
    partial_target_calls.clear()
    runtime = {"injected_value": "runtime-object"}

    partial_call = instantiate(
        {
            "_target_": "tests.support.config_samples:record_partial_target",
            "_partial_": True,
            "_args_": [
                {"_target_": "tests.support.config_samples:log_and_return", "tag": "arg", "value": "A"},
            ],
            "_inject_": {"runtime_value": "injected_value"},
            "left": {"_target_": "tests.support.config_samples:log_and_return", "tag": "kw", "value": "K"},
            "right": {"_target_": "tests.support.config_samples:log_and_return", "tag": "kw-right", "value": "R"},
            "sequence": (
                {"_target_": "tests.support.config_samples:log_and_return", "tag": "seq-0", "value": "S0"},
                {"_target_": "tests.support.config_samples:log_and_return", "tag": "seq-1", "value": "S1"},
            ),
            "value": "static",
        },
        runtime=runtime,
    )

    assert partial_target_calls == []
    assert isinstance(partial_call, partial)
    assert partial_call.args == ("A",)
    assert partial_call.keywords["left"] == "K"
    assert partial_call.keywords["right"] == "R"
    assert partial_call.keywords["sequence"] == ["S0", "S1"]
    assert partial_call.keywords["runtime_value"] == "runtime-object"
    assert partial_call.keywords["value"] == "static"

    result = partial_call()
    assert partial_target_calls == [
        (
            ("A",),
            {
                "left": "K",
                "right": "R",
                "sequence": ["S0", "S1"],
                "runtime_value": "runtime-object",
                "value": "static",
            },
        )
    ]
    assert isinstance(result, dict)
