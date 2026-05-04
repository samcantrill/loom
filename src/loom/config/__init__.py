"""Config package."""

from __future__ import annotations

from types import ModuleType
from typing import TYPE_CHECKING, Final

import sys

from loom.errors import ConfigError

from ._optional import require_config_dependencies

if TYPE_CHECKING:
    from .api import ComposedConfig, compose_config, instantiate, register_recipe
    from .recipes import Recipe, RecipeCatalog


_RESOLVED_SYMBOLS: dict[str, object] = {
    "ConfigError": ConfigError,
}
_OPTIONAL_SYMBOLS: Final = frozenset(
    {"ComposedConfig", "compose_config", "register_recipe", "Recipe", "RecipeCatalog", "instantiate"}
)

def _resolve_optional_symbol(name: str) -> object:
    require_config_dependencies()

    match name:
        case "ComposedConfig" | "compose_config" | "register_recipe":
            from . import api

            return getattr(api, name)
        case "Recipe" | "RecipeCatalog":
            from . import recipes

            return getattr(recipes, name)
        case "instantiate":
            from .api import instantiate as _instantiate

            return _instantiate
    raise AssertionError(f"unexpected config symbol name: {name!r}")


class _ConfigPackage(ModuleType):
    def __getattr__(self, name: str) -> object:
        if name in _RESOLVED_SYMBOLS:
            return _RESOLVED_SYMBOLS[name]
        if name not in _OPTIONAL_SYMBOLS:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

        value = _resolve_optional_symbol(name)
        _RESOLVED_SYMBOLS[name] = value
        setattr(self, name, value)
        return value

    def __setattr__(self, name: str, value: object) -> None:
        if name == "instantiate" and isinstance(value, ModuleType):
            value = _resolve_optional_symbol("instantiate")
        super().__setattr__(name, value)

    def __dir__(self) -> list[str]:
        return sorted(__all__)


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
