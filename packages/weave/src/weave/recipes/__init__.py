"""Recipe APIs for trusted config composition."""

from .base import ConfigRecipe, Recipe, RecipeImplementation, RecipeMapping, RecipeOutput
from .catalog import RecipeCatalog
from .expansion import expand_recipes
from .manifest import RecipeManifestRecord
from .errors import (
    DuplicateRecipeError,
    InvalidRecipeOutputError,
    RecipeExpansionError,
    RecipeRegistrationError,
    ReservedConfigKeyError,
    UnknownRecipeError,
)

__all__ = [
    "ConfigRecipe",
    "Recipe",
    "RecipeImplementation",
    "RecipeMapping",
    "RecipeOutput",
    "RecipeCatalog",
    "RecipeManifestRecord",
    "expand_recipes",
    "RecipeRegistrationError",
    "DuplicateRecipeError",
    "UnknownRecipeError",
    "RecipeExpansionError",
    "InvalidRecipeOutputError",
    "ReservedConfigKeyError",
]
