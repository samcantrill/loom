"""Target import helpers for `_target_` configuration directives."""

from __future__ import annotations

import importlib
from typing import cast

from loom.config.errors import ConfigErrorContext, TargetImportError
from loom.serialization import PlainData, to_plain_data


def import_target(target: str, *, path: str = "$") -> object:
    """Import a Python object from dotted or colon syntax."""

    if not isinstance(target, str) or not target:
        raise TargetImportError(
            f"Target path must be text at {path}; got {type(target).__name__}",
            context=_target_context(
                code="invalid_target_type",
                path=path,
                expected="non-empty string",
                actual=type(target).__name__,
            ),
        )

    if target.count(":") > 1:
        raise TargetImportError(
            f"Invalid target path {target!r} at {path}: only one ':' is allowed",
            context=_target_context(
                code="invalid_target_syntax",
                path=path,
                expected="dotted.path.Object or module:Object",
                actual="multiple colon separators",
                details={"target": target},
            ),
        )

    if ":" in target:
        module_path, object_path = target.split(":", 1)
        if "." in object_path:
            raise TargetImportError(
                f"Invalid target path {target!r} at {path}: colon form does not support dotted object path",
                context=_target_context(
                    code="invalid_target_syntax",
                    path=path,
                    expected="module:Object",
                    actual="dotted object path in colon form",
                    details={"target": target},
                ),
            )
        return _load_object(module_path=module_path, object_name=object_path, path=path)

    if target.count(".") < 1:
        raise TargetImportError(
            f"Invalid target path {target!r} at {path}: dotted or colon form required",
            context=_target_context(
                code="invalid_target_syntax",
                path=path,
                expected="dotted.path.Object or module:Object",
                actual="missing module/object separator",
                details={"target": target},
            ),
        )

    module_path, object_path = target.rsplit(".", 1)
    return _load_object(module_path=module_path, object_name=object_path, path=path)


def _load_object(*, module_path: str, object_name: str, path: str) -> object:
    module_path = module_path.strip()
    object_name = object_name.strip()

    if not module_path or not object_name:
        raise TargetImportError(
            f"Invalid target path at {path}: {module_path!r}:{object_name!r}",
            context=_target_context(
                code="invalid_target_syntax",
                path=path,
                expected="non-empty module and object names",
                actual="empty module or object",
                details={"module_path": module_path, "object_name": object_name},
            ),
        )

    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        raise TargetImportError(
            f"Failed to import module {module_path!r} for _target_ at {path}",
            context=_target_context(
                code="target_module_import_failed",
                path=path,
                expected="importable module",
                actual=module_path,
                details={"module_path": module_path, "exception_type": type(exc).__name__},
            ),
        ) from exc

    try:
        target = getattr(module, object_name)
    except AttributeError as exc:  # noqa: BLE001
        raise TargetImportError(
            f"Target object {object_name!r} not found in {module_path!r} at {path}",
            context=_target_context(
                code="target_object_not_found",
                path=path,
                expected="object exported by module",
                actual=object_name,
                details={"module_path": module_path, "object_name": object_name},
            ),
        ) from exc

    return target


def _target_context(
    *,
    code: str,
    path: str,
    expected: object | None = None,
    actual: object | None = None,
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
        directive="_target_",
        remediation=_target_remediation(code),
        details=cast(dict[str, PlainData], to_plain_data({"stage": "target_import", **(details or {})})),
    )


def _target_remediation(code: str) -> str | None:
    if code == "invalid_target_syntax":
        return "Use dotted module.object syntax or module:Object syntax."
    if code == "target_module_import_failed":
        return "Install the package or correct the target module path."
    if code == "target_object_not_found":
        return "Export the named object or correct the target object name."
    return None
