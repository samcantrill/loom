"""Unit tests for recipe catalog behavior."""

import pytest

from loom.config.errors import DuplicateRecipeError, RecipeRegistrationError, UnknownRecipeError
from loom.config.recipes import RecipeCatalog
from tests.support.config_samples import ArgumentRecipe, DownstreamRecipe, function_recipe


def test_catalog_register_lookup_and_order() -> None:
    catalog = RecipeCatalog()
    catalog.register("a", function_recipe)
    catalog.register("b", ArgumentRecipe)
    catalog.register("c", DownstreamRecipe)

    assert catalog.names() == ("a", "b", "c")
    assert catalog.get("b") is ArgumentRecipe
    assert catalog.get("c") is DownstreamRecipe
    assert ("a", function_recipe) in catalog.items()
    assert catalog.__len__() == 3
    assert "a" in catalog


def test_catalog_lookup_unknown_recipe() -> None:
    catalog = RecipeCatalog()
    catalog.register("a", function_recipe)
    with pytest.raises(UnknownRecipeError, match="Unknown recipe 'missing'"):
        catalog.get("missing")


def test_catalog_duplicate_detection() -> None:
    catalog = RecipeCatalog()
    catalog.register("recipe", function_recipe)
    with pytest.raises(DuplicateRecipeError):
        catalog.register("recipe", DownstreamRecipe)


def test_catalog_replace_preserves_order() -> None:
    catalog = RecipeCatalog()
    catalog.register("first", function_recipe)
    catalog.register("second", ArgumentRecipe)
    catalog.register("third", DownstreamRecipe)
    catalog.register("second", function_recipe, replace=True)

    assert catalog.names() == ("first", "second", "third")
    assert catalog.get("second") is function_recipe


def test_catalog_invalid_name_and_implementation() -> None:
    catalog = RecipeCatalog()
    with pytest.raises(RecipeRegistrationError, match="Recipe name must be a non-empty string"):
        catalog.register("", function_recipe)

    class NotCallable:
        pass

    with pytest.raises(RecipeRegistrationError, match="callable|ConfigRecipe"):
        catalog.register("bad", NotCallable())  # type: ignore[arg-type]


def test_catalog_to_dict() -> None:
    catalog = RecipeCatalog()
    catalog.register("a", function_recipe)
    payload = catalog.to_dict()
    assert payload["a"] == "tests.support.config_samples:function_recipe"


def test_catalog_from_dict_is_unsupported() -> None:
    catalog = RecipeCatalog()
    with pytest.raises(RecipeRegistrationError, match="not supported in v0"):
        catalog.from_dict({"x": function_recipe})  # type: ignore[arg-type]
