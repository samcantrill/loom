"""Recipe protocols and typed recipe base classes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol, TypeAlias, runtime_checkable

from pydantic import BaseModel, ConfigDict


@runtime_checkable
class ConfigRecipe(Protocol):
    """Protocol for contract-style recipe objects."""

    def expand(self) -> Mapping[str, Any]:
        """Return a plain-data mapping to replace a `_recipe_` block."""


class Recipe(BaseModel):
    """Base class for validated typed recipe input objects."""

    model_config = ConfigDict(extra="forbid")

    def expand(self) -> Mapping[str, Any]:
        raise NotImplementedError


RecipeMapping = Mapping[str, Any]
RecipeOutput = Mapping[str, Any]
RecipeImplementation: TypeAlias = Callable[..., object] | type[Any]

__all__ = ["ConfigRecipe", "Recipe", "RecipeImplementation", "RecipeMapping", "RecipeOutput"]
