"""Stage construction helpers owned by the pipeline layer."""

from __future__ import annotations

import importlib

from loom.pipeline.errors import StageContractError
from loom.pipeline.specs import StageFactorySpec
from .stage import Stage


__all__ = ["import_stage_target", "construct_stage"]


def import_stage_target(*, target_path: str, path: str) -> object:
    """Import a stage factory target using dotted or colon syntax."""

    if not isinstance(target_path, str) or not target_path:
        raise StageContractError(f"{path} must be a non-empty string")

    if target_path.count(":") > 1:
        raise StageContractError(
            f"{path} is invalid: only one ':' is allowed in stage target paths"
        )

    if ":" in target_path:
        module_path, object_path = target_path.split(":", 1)
        if "." in object_path:
            raise StageContractError(
                f"{path} is invalid: colon-form stage targets must not use dotted object paths"
            )
    else:
        if target_path.count(".") < 1:
            raise StageContractError(
                f"{path} is invalid: dotted or single-colon stage target path required"
            )
        module_path, object_path = target_path.rsplit(".", 1)

    return _load_object(module_path=module_path.strip(), object_name=object_path.strip(), path=path)


def _load_object(*, module_path: str, object_name: str, path: str) -> object:
    if not module_path or not object_name:
        raise StageContractError(f"{path} is invalid: module/object path missing")

    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        raise StageContractError(
            f"failed to import module {module_path!r} for stage target at {path}"
        ) from exc

    try:
        return getattr(module, object_name)
    except AttributeError as exc:
        raise StageContractError(
            f"target object {object_name!r} not found in module {module_path!r} for stage target at {path}"
        ) from exc


def construct_stage(*, factory: StageFactorySpec, stage_path: str) -> Stage:
    """Construct a Stage from factory metadata."""

    target = import_stage_target(target_path=factory.target_path, path=f"{stage_path}.factory._target_")
    try:
        if isinstance(target, type):
            candidate = target(**factory.init)
        elif isinstance(target, Stage):
            if factory.init:
                raise StageContractError(
                    f"{stage_path}.factory.init must be empty when the stage target is an instance"
                )
            candidate = target
        elif callable(target):
            candidate = target(**factory.init)
        else:
            raise StageContractError(
                f"{stage_path}.factory._target_ is neither a class, callable, nor Stage instance"
            )
    except StageContractError:
        raise
    except TypeError as exc:
        raise StageContractError(
            f"{stage_path}.factory.init could not construct stage from {stage_path}.factory._target_"
        ) from exc
    except Exception as exc:
        raise StageContractError(
            f"{stage_path}.factory._target_ could not construct stage: {exc}"
        ) from exc

    if not isinstance(candidate, Stage):
        raise StageContractError(
            f"{stage_path}.factory._target_ did not construct a Stage-compatible object"
        )
    return candidate
