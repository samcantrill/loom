"""Public config composition API."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn, Sequence

from loom.fingerprints import Fingerprint
from loom.errors import ConfigError
from loom.serialization import PlainData

from .provenance import ConfigProvenance


@dataclass(frozen=True, slots=True)
class ComposedConfig:
    resolved: dict[str, PlainData]
    redacted: dict[str, PlainData]
    provenance: ConfigProvenance
    recipe_manifest: tuple[dict[str, PlainData], ...]
    fingerprint: Fingerprint


def compose_config(
    config_path: str | Path,
    overlays: Sequence[str | Path] = (),
    overrides: Sequence[str] = (),
    recipe_catalog: object | None = None,
) -> ComposedConfig:
    from .compose import compose_config as _compose_config

    return _compose_config(
        config_path=config_path,
        overlays=overlays,
        overrides=overrides,
        recipe_catalog=recipe_catalog,
    )


def instantiate(*_args: object, **_kwargs: object) -> NoReturn:
    raise ConfigError("instantiate is not supported in Phase 5")


def register_recipe(*_args: object, **_kwargs: object) -> NoReturn:
    raise ConfigError("register_recipe is not supported in Phase 5")


__all__ = ["ComposedConfig", "compose_config", "instantiate", "register_recipe"]
