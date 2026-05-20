"""Recursive `_target_` object construction."""

import re
from collections.abc import Mapping, Sequence
from functools import partial
from typing import Any, cast

from ..errors import (
    ConfigErrorContext,
    ReservedConfigKeyError,
    RuntimeInjectionError,
    TargetInstantiationError,
)
from ..plain import PlainData, to_plain_data

from . import injection
from .targets import import_target

_TARGET_RESERVED_KEYS = frozenset({"_target_", "_args_", "_partial_", "_inject_", "_recipe_"})
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def instantiate(value: object, *, runtime: Mapping[str, object] | None = None) -> object:
    """Instantiate `_target_` mappings recursively into Python objects."""

    if runtime is not None and not isinstance(runtime, Mapping):
        raise RuntimeInjectionError(
            "runtime must be a mapping when provided",
            context=_instantiate_context(
                code="runtime_not_mapping",
                path="$",
                directive="_inject_",
                expected="mapping",
                actual=type(runtime).__name__,
            ),
        )
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
            f"Found _recipe_ in instantiate input at {path}; compose_config() must expand recipes first",
            context=_instantiate_context(
                code="unexpanded_recipe_in_instantiate",
                path=path,
                directive="_recipe_",
                remediation="Call compose_config() before instantiating target mappings.",
            ),
        )

    if "_target_" not in mapping:
        if "_args_" in mapping:
            raise _reserved_instantiation_key("_args_", path=path)
        if "_partial_" in mapping:
            raise _reserved_instantiation_key("_partial_", path=path)
        if "_inject_" in mapping:
            raise _reserved_instantiation_key("_inject_", path=path)
        if "_recipe_" in mapping:
            raise _reserved_instantiation_key("_recipe_", path=path)

        return {key: _instantiate(value=value, runtime=runtime, path=_child_path(path, key)) for key, value in mapping.items()}

    target = mapping.get("_target_")
    if not isinstance(target, str):
        raise ReservedConfigKeyError(
            f"_target_ must be a non-empty string at {path}",
            context=_instantiate_context(
                code="invalid_target_value",
                path=_child_path(path, "_target_"),
                directive="_target_",
                expected="non-empty string",
                actual=type(target).__name__,
            ),
        )
    if not target:
        raise ReservedConfigKeyError(
            f"_target_ must be a non-empty string at {path}",
            context=_instantiate_context(
                code="invalid_target_value",
                path=_child_path(path, "_target_"),
                directive="_target_",
                expected="non-empty string",
                actual="empty string",
            ),
        )

    args_value = mapping.get("_args_", ())
    if not isinstance(args_value, Sequence) or isinstance(args_value, (str, bytes, bytearray)):
        raise ReservedConfigKeyError(
            f"_args_ must be a sequence at {path}",
            context=_instantiate_context(
                code="invalid_target_args",
                path=_child_path(path, "_args_"),
                directive="_args_",
                expected="sequence",
                actual=type(args_value).__name__,
            ),
        )

    inject_value = mapping.get("_inject_")
    if "_partial_" in mapping and not isinstance(mapping["_partial_"], bool):
        raise ReservedConfigKeyError(
            f"_partial_ must be a bool at {path}",
            context=_instantiate_context(
                code="invalid_target_partial",
                path=_child_path(path, "_partial_"),
                directive="_partial_",
                expected="bool",
                actual=type(mapping["_partial_"]).__name__,
            ),
        )

    if "_recipe_" in mapping:
        raise _reserved_instantiation_key("_recipe_", path=path)

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
        raise TargetInstantiationError(
            f"Target {target} at {path} is not callable",
            context=_instantiate_context(
                code="target_not_callable",
                path=path,
                directive="_target_",
                expected="callable",
                actual=type(target_callable).__name__,
                details={"target": target},
            ),
        )

    if partial_mode:
        return partial(target_callable, *args, **kwargs)

    try:
        return target_callable(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        raise TargetInstantiationError(
            f"Failed to instantiate {_target_name(target_callable)!r} at {path}",
            context=_instantiate_context(
                code="target_instantiation_failed",
                path=path,
                directive="_target_",
                details={
                    "target": target,
                    "target_name": _target_name(target_callable),
                    "exception_type": type(exc).__name__,
                },
            ),
        ) from exc


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


def _reserved_instantiation_key(key: str, *, path: str) -> ReservedConfigKeyError:
    return ReservedConfigKeyError(
        f"{key} is not valid in non-target mappings at {path}",
        context=_instantiate_context(
            code="reserved_instantiation_key",
            path=path,
            directive=key,
            remediation="Use reserved instantiation directives only inside mappings with _target_.",
            details={"reserved_key": key},
        ),
    )


def _instantiate_context(
    *,
    code: str,
    path: str,
    directive: str,
    expected: object | None = None,
    actual: object | None = None,
    remediation: str | None = None,
    details: dict[str, object] | None = None,
) -> ConfigErrorContext:
    return ConfigErrorContext(
        code=code,
        source_kind="target",
        source_order=0,
        source_path="<target>",
        config_path=path,
        expected=to_plain_data(expected) if expected is not None else None,
        actual=to_plain_data(actual) if actual is not None else None,
        directive=directive,
        remediation=remediation or _instantiate_remediation(code),
        details=cast(dict[str, PlainData], to_plain_data({"stage": "target_instantiation", **(details or {})})),
    )


def _instantiate_remediation(code: str) -> str | None:
    if code == "invalid_target_value":
        return "Set _target_ to a non-empty dotted or colon import path."
    if code == "invalid_target_args":
        return "Set _args_ to a list or tuple of positional arguments."
    if code == "invalid_target_partial":
        return "Set _partial_ to true or false."
    if code == "target_not_callable":
        return "Point _target_ at a callable object."
    return None
