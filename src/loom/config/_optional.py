"""Helpers for config optional-dependency behavior."""

from __future__ import annotations

import importlib

from .errors import MissingConfigDependencyError

_CONFIG_DEPENDENCIES = ("yaml", "omegaconf", "pydantic")
_CONFIG_EXTRA_HINT = "Install with `loom[config]`"


def require_config_dependencies() -> None:
    """Raise a config-owned error if an optional config dependency is unavailable."""

    missing: list[str] = []
    for module_name in _CONFIG_DEPENDENCIES:
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError:
            missing.append(module_name)

    if not missing:
        return

    raise MissingConfigDependencyError(
        "Missing optional configuration dependencies "
        f"({', '.join(sorted(missing))}); {_CONFIG_EXTRA_HINT} before importing config symbols."
    )
