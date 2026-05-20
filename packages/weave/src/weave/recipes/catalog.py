"""Recipe catalog for named, trusted config recipes."""

from __future__ import annotations

import re
from collections.abc import Mapping

from ..plain import PlainData

from ..errors import DuplicateRecipeError, RecipeRegistrationError, UnknownRecipeError
from .base import RecipeImplementation

_RECIPE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class RecipeCatalog:
    """Explicit registry for named configuration recipes."""

    def __init__(self) -> None:
        self._recipes: dict[str, RecipeImplementation] = {}
        self._order: list[str] = []

    def register(self, name: str, recipe: RecipeImplementation, *, replace: bool = False) -> None:
        _validate_name(name)
        _validate_recipe_implementation(name=name, recipe=recipe)
        if name in self._recipes:
            if not replace:
                raise DuplicateRecipeError(f"Recipe {name!r} is already registered")
            self._recipes[name] = recipe
            return
        self._recipes[name] = recipe
        self._order.append(name)

    def get(self, name: str) -> RecipeImplementation:
        if name not in self._recipes:
            raise UnknownRecipeError(f"Unknown recipe {name!r}; available recipes: {', '.join(self.names()) or 'none'}")
        return self._recipes[name]

    def lookup(self, name: str) -> RecipeImplementation:
        return self.get(name)

    def __contains__(self, name: object) -> bool:
        return name in self._recipes

    def __len__(self) -> int:
        return len(self._order)

    def names(self) -> tuple[str, ...]:
        return tuple(self._order)

    def items(self) -> tuple[tuple[str, RecipeImplementation], ...]:
        return tuple((name, self._recipes[name]) for name in self._order)

    def to_dict(self) -> dict[str, PlainData]:
        output: dict[str, PlainData] = {name: _normalize_recipe_target(recipe) for name, recipe in self.items()}
        return output

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "RecipeCatalog":
        del payload
        raise RecipeRegistrationError("Deserializing recipes from plain data is not supported in v0")


def _validate_name(name: str) -> None:
    if not isinstance(name, str) or not name:
        raise RecipeRegistrationError(f"Recipe name must be a non-empty string, got {name!r}")
    if not _RECIPE_NAME_RE.match(name):
        raise RecipeRegistrationError(f"Invalid recipe name {name!r}; expected /{_RECIPE_NAME_RE.pattern}/")


def _validate_recipe_implementation(*, name: str, recipe: RecipeImplementation) -> None:
    if isinstance(recipe, type):
        return
    if callable(recipe):
        return

    raise RecipeRegistrationError(f"Recipe {name!r} must be a callable recipe implementation or recipe class")


def _normalize_recipe_target(recipe: RecipeImplementation) -> str:
    target = recipe
    if isinstance(recipe, type):
        target = recipe
    module = getattr(target, "__module__", "<unknown>")
    qualname = getattr(target, "__qualname__", getattr(target, "__name__", "<unknown>"))
    return f"{module}:{qualname}"
