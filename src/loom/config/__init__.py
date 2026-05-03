"""Config package skeleton."""

from typing import NoReturn

from loom.errors import ConfigError


def compose_config(*_args: object, **_kwargs: object) -> NoReturn:
    raise ConfigError("compose_config is not implemented in Phase 1; implement in Phase 4.")


def instantiate(*_args: object, **_kwargs: object) -> NoReturn:
    raise ConfigError("instantiate is not implemented in Phase 1; implement in Phase 4.")


def register_recipe(*_args: object, **_kwargs: object) -> NoReturn:
    raise ConfigError("register_recipe is not implemented in Phase 1; implement in Phase 5.")


__all__ = ["ConfigError", "compose_config", "instantiate", "register_recipe"]
