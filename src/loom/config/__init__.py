"""Config package."""

from __future__ import annotations

from types import ModuleType

import sys

from loom.errors import ConfigError

from .api import ComposedConfig, compose_config, register_recipe
from .api import instantiate as _instantiate
from .recipes import Recipe, RecipeCatalog

instantiate = _instantiate


class _ConfigPackage(ModuleType):
    def __setattr__(self, name: str, value: object) -> None:
        if name == "instantiate" and isinstance(value, ModuleType):
            value = _instantiate
        super().__setattr__(name, value)


_module = sys.modules[__name__]
if not isinstance(_module, _ConfigPackage):
    _module.__class__ = _ConfigPackage

__all__ = [
    "ConfigError",
    "ComposedConfig",
    "Recipe",
    "RecipeCatalog",
    "compose_config",
    "instantiate",
    "register_recipe",
]
