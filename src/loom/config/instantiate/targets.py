"""Target import helpers for `_target_` configuration directives."""

from __future__ import annotations

from collections.abc import Callable

import importlib

from loom.config.errors import TargetImportError


def import_target(target: str, *, path: str = "$") -> object:
    """Import a Python object from dotted or colon syntax."""

    if not isinstance(target, str) or not target:
        raise TargetImportError(f"Target path must be text at {path}; got {type(target).__name__}")

    if target.count(":") > 1:
        raise TargetImportError(f"Invalid target path {target!r} at {path}: only one ':' is allowed")

    if ":" in target:
        module_path, object_path = target.split(":", 1)
        if "." in object_path:
            raise TargetImportError(f"Invalid target path {target!r} at {path}: colon form does not support dotted object path")
        return _load_object(module_path=module_path, object_name=object_path, path=path)

    if target.count(".") < 1:
        raise TargetImportError(f"Invalid target path {target!r} at {path}: dotted or colon form required")

    module_path, object_path = target.rsplit(".", 1)
    return _load_object(module_path=module_path, object_name=object_path, path=path)


def _load_object(*, module_path: str, object_name: str, path: str) -> object:
    module_path = module_path.strip()
    object_name = object_name.strip()

    if not module_path or not object_name:
        raise TargetImportError(f"Invalid target path at {path}: {module_path!r}:{object_name!r}")

    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        raise TargetImportError(f"Failed to import module {module_path!r} for _target_ at {path}") from exc

    try:
        target = getattr(module, object_name)
    except AttributeError as exc:  # noqa: BLE001
        raise TargetImportError(f"Target object {object_name!r} not found in {module_path!r} at {path}") from exc

    return target
