"""Recursive `_target_` object construction."""

import re
from collections.abc import Mapping, Sequence
from functools import partial
from typing import Any

from loom.config.errors import (
    ReservedConfigKeyError,
    RuntimeInjectionError,
    TargetInstantiationError,
)

from . import injection
from .targets import import_target

_TARGET_RESERVED_KEYS = frozenset({"_target_", "_args_", "_partial_", "_inject_", "_recipe_"})
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def instantiate(value: object, *, runtime: Mapping[str, object] | None = None) -> object:
    """Instantiate `_target_` mappings recursively into Python objects."""

    if runtime is not None and not isinstance(runtime, Mapping):
        raise RuntimeInjectionError("runtime must be a mapping when provided")
    return _instantiate(value=value, runtime=runtime, path="$")


def _instantiate(*, value: object, runtime: Mapping[str, object] | None, path: str) -> object:
    if isinstance(value, Mapping):
        return _instantiate_mapping(mapping=value, runtime=runtime, path=path)

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_instantiate(value=item, runtime=runtime, path=f"{path}[{index}]") for index, item in enumerate(value)]

    return value


def _instantiate_mapping(*, mapping: Mapping[str, Any], runtime: Mapping[str, object] | None, path: str) -> object:
    if "_recipe_" in mapping:
        raise ReservedConfigKeyError(
            f"Found _recipe_ in instantiate input at {path}; compose_config() must expand recipes first"
        )

    if "_target_" not in mapping:
        if "_args_" in mapping:
            raise ReservedConfigKeyError(f"_args_ is not valid in non-target mappings at {path}")
        if "_partial_" in mapping:
            raise ReservedConfigKeyError(f"_partial_ is not valid in non-target mappings at {path}")
        if "_inject_" in mapping:
            raise ReservedConfigKeyError(f"_inject_ is not valid in non-target mappings at {path}")
        if "_recipe_" in mapping:
            raise ReservedConfigKeyError(f"_recipe_ is not valid in non-target mappings at {path}")

        return {key: _instantiate(value=value, runtime=runtime, path=_child_path(path, key)) for key, value in mapping.items()}

    target = mapping.get("_target_")
    if not isinstance(target, str):
        raise ReservedConfigKeyError(f"_target_ must be a non-empty string at {path}")
    if not target:
        raise ReservedConfigKeyError(f"_target_ must be a non-empty string at {path}")

    args_value = mapping.get("_args_", ())
    if not isinstance(args_value, Sequence) or isinstance(args_value, (str, bytes, bytearray)):
        raise ReservedConfigKeyError(f"_args_ must be a sequence at {path}")

    inject_value = mapping.get("_inject_")
    if "_partial_" in mapping and not isinstance(mapping["_partial_"], bool):
        raise ReservedConfigKeyError(f"_partial_ must be a bool at {path}")

    if "_recipe_" in mapping:
        raise ReservedConfigKeyError(f"_recipe_ is not valid alongside _target_ at {path}")

    kwargs: dict[str, object] = {
        key: _instantiate(value=val, runtime=runtime, path=_child_path(path, key))
        for key, val in mapping.items()
        if key not in _TARGET_RESERVED_KEYS
    }
    args = [_instantiate(value=arg, runtime=runtime, path=f"{path}[_args_][{index}]") for index, arg in enumerate(args_value)]
    partial_mode = bool(mapping.get("_partial_", False))

    if inject_value is not None:
        kwargs = injection.apply_injected_kwargs(kwargs=kwargs, injected=inject_value, runtime=runtime, path=_child_path(path, "_inject_"))

    target_callable = import_target(target, path=_child_path(path, "_target_"))
    if not callable(target_callable):
        raise TargetInstantiationError(f"Target {target} at {path} is not callable")

    if partial_mode:
        return partial(target_callable, *args, **kwargs)

    try:
        return target_callable(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        raise TargetInstantiationError(f"Failed to instantiate {_target_name(target_callable)!r} at {path}") from exc


def _target_name(target: object) -> str:
    return f"{getattr(target, '__module__', '<unknown>')}.{getattr(target, '__qualname__', getattr(target, '__name__', 'target'))}"


def _child_path(path: str, key: str | int) -> str:
    if isinstance(key, int):
        return f"{path}[{key}]"
    if _IDENTIFIER_RE.fullmatch(key):
        if path == "$":
            return key
        return f"{path}.{key}"
    if path == "$":
        return f"[{key!r}]"
    return f"{path}[{key!r}]"
