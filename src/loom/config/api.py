"""Public config composition API."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from loom.fingerprints import Fingerprint
from loom.errors import ConfigError
from loom.serialization import PlainData
from loom.config.errors import ConfigValidationError

from .provenance import ConfigProvenance
from .recipes import RecipeCatalog, RecipeImplementation


__default_recipe_catalog: RecipeCatalog | None = None


@dataclass(frozen=True, slots=True)
class ComposedConfig:
    resolved: dict[str, PlainData]
    redacted: dict[str, PlainData]
    provenance: ConfigProvenance
    recipe_manifest: tuple[dict[str, PlainData], ...]
    fingerprint: Fingerprint


def compose_config(
    config_path: str | Path,
    overlays: list[str | Path] | tuple[str | Path, ...] = (),
    overrides: list[str] | tuple[str, ...] = (),
    recipe_catalog: RecipeCatalog | None = None,
) -> ComposedConfig:
    from .compose import compose_config as _compose_config

    if overlays is None:
        raise ConfigValidationError("overlays may not be None")
    if overrides is None:
        raise ConfigValidationError("overrides may not be None")

    return _compose_config(
        config_path=config_path,
        overlays=tuple(overlays),
        overrides=tuple(overrides),
        recipe_catalog=recipe_catalog,
    )


def instantiate(value: object, *, runtime: Mapping[str, object] | None = None) -> object:
    from .instantiate.recursive import instantiate as _instantiate

    return _instantiate(value=value, runtime=runtime)


def register_recipe(name: str, recipe: RecipeImplementation, *, replace: bool = False) -> None:
    _get_default_recipe_catalog().register(name=name, recipe=recipe, replace=replace)


def _get_default_recipe_catalog() -> RecipeCatalog:
    global __default_recipe_catalog
    if __default_recipe_catalog is None:
        __default_recipe_catalog = RecipeCatalog()
    return __default_recipe_catalog


__all__ = [
    "ComposedConfig",
    "compose_config",
    "instantiate",
    "register_recipe",
]
