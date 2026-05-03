"""Synthetic recipe and target helpers for config phase tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loom.config.recipes import Recipe


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
