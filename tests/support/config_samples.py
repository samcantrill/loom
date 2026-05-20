"""Synthetic recipe and target helpers for config phase tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from weave.recipes import Recipe


class RuntimePlaceholder:
    """Simple payload holder used by runtime-injection tests."""

    def __init__(self, value: object) -> None:
        self.value = value


NON_CALLABLE_TARGET = object()


class EchoService:
    def __init__(self, value: object) -> None:
        self.value = value


class AddService:
    def __init__(self, left: int, right: int = 0) -> None:
        self.left = left
        self.right = right

    def total(self) -> int:
        return self.left + self.right


class Concat:
    """Target class used by import/instantiate tests."""

    def __init__(self, left: str, right: str = "") -> None:
        self.left = left
        self.right = right

    @property
    def value(self) -> str:
        return f"{self.left}{self.right}"


class Parent:
    """Container used to ensure dotted targets do not recurse through nested attributes."""

    class Inner:
        pass


construction_event_log: list[str] = []
partial_target_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []


def reset_instantiate_probe_state() -> None:
    """Clear probe state used by instantiation contract tests."""
    construction_event_log.clear()
    partial_target_calls.clear()


def log_and_return(*, tag: str, value: object) -> object:
    """Emit an ordered construction marker and return the provided value."""
    construction_event_log.append(tag)
    return value


class ConstructionProbeTarget:
    """Target object that records bottom-up instantiation order."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        construction_event_log.append("parent")
        self.args = args
        self.kwargs = kwargs


def record_partial_target(*args: object, **kwargs: object) -> dict[str, object]:
    """Target callable used for `_partial_` contract tests."""
    partial_target_calls.append((args, kwargs))
    return {"args": list(args), "kwargs": dict(kwargs)}


def concat(prefix: str, suffix: str = "") -> str:
    return prefix + suffix


class ArgumentRecipe(Recipe):
    value: str

    def expand(self) -> dict[str, Any]:
        return {"value": self.value}


@dataclass
class DownstreamRecipe:
    value: str
    marker: str = "downstream"

    def expand(self) -> dict[str, Any]:
        return {"value": f"{self.marker}:{self.value}"}


def function_recipe(value: str, prefix: str = "", repeat: int = 1) -> dict[str, Any]:
    return {"value": f"{prefix}{value}" * repeat}


def argument_recipe(value: str, offset: int = 0) -> dict[str, Any]:
    return {"value": f"{value}:{offset}"}


def nested_argument_recipe(value: str) -> dict[str, Any]:
    return {
        "outer": {
            "value": value,
            "inner": {"_recipe_": "dataclass", "value": f"{value}-inner", "marker": "seeded"},
        }
    }


def composed_output_recipe(value: str) -> dict[str, Any]:
    return {
        "value": value,
        "resolved": "${value}-resolved",
        "nested": {"_recipe_": "dataclass", "value": "${value}-child", "marker": "nested"},
    }


def nested_output_recipe(value: str) -> dict[str, Any]:
    return {
        "outer": {
            "value": value,
            "inner": {"_recipe_": "downstream", "value": f"{value}-inner", "marker": "nested"},
        }
    }


@dataclass
class NestedOutputRecipe:
    value: str

    def expand(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "nested": {"_recipe_": "argument", "value": f"{self.value}-child"},
        }
