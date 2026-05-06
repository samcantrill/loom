"""Recipe expansion orchestration."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, cast

from loom.serialization import PlainData, to_plain_data
from loom.serialization.errors import PlainDataError
from loom.config.errors import (
    ConfigErrorContext,
    ConfigInterpolationError,
    InvalidRecipeOutputError,
    RecipeExpansionError,
    ReservedConfigKeyError,
)

from .base import ConfigRecipe, Recipe, RecipeImplementation
from .catalog import RecipeCatalog
from .manifest import RecipeManifestRecord

_RESERVED_KEYS = frozenset({"_target_", "_args_", "_partial_", "_inject_", "_recipe_"})
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SEGMENT_RE = re.compile(r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<indices>(?:\[[0-9]+\])*)")
_INTERPOLATION_RE = re.compile(r"\$\{([^{}]+)\}")
_RESOLVER_IN_KEY_RE = re.compile(r"\$\{")


def resolve_recipe_argument_interpolation(
    config: Mapping[str, PlainData],
    *,
    path: str = "$",
) -> dict[str, PlainData]:
    """Resolve interpolation only inside recipe argument values."""

    root = to_plain_data(config, path=path)
    if not isinstance(root, dict):
        raise ConfigInterpolationError(
            f"Recipe argument resolution root must be a mapping at {path}",
            context=_recipe_context(
                code="recipe_argument_root_not_mapping",
                path=path,
                stage="recipe_argument_interpolation",
                expected="mapping",
                actual=type(root).__name__,
            ),
        )
    resolved, _ = _resolve_recipe_arguments(root, root=root, path=path)
    if not isinstance(resolved, dict):
        raise ConfigInterpolationError(
            f"Recipe argument resolution root must be a mapping at {path}",
            context=_recipe_context(
                code="recipe_argument_root_not_mapping",
                path=path,
                stage="recipe_argument_interpolation",
                expected="mapping",
                actual=type(resolved).__name__,
            ),
        )
    return resolved


def expand_recipes(
    config: Mapping[str, PlainData],
    *,
    catalog: RecipeCatalog,
    path: str = "$",
) -> tuple[dict[str, PlainData], tuple[dict[str, PlainData], ...]]:
    """Expand all `_recipe_` directives in a config mapping."""

    plain = to_plain_data(config, path=path)
    expanded, manifest = _expand_node(plain, catalog=catalog, path=path)
    if not isinstance(expanded, dict):
        raise InvalidRecipeOutputError(
            f"Recipe expansion root must remain a mapping at {path}",
            context=_recipe_context(
                code="recipe_root_not_mapping",
                path=path,
                stage="recipe_expansion",
                expected="mapping",
                actual=type(expanded).__name__,
            ),
        )
    return expanded, tuple(item.to_dict() for item in manifest)


def _resolve_recipe_arguments(node: Any, *, root: Mapping[str, Any], path: str) -> tuple[Any, bool]:
    if isinstance(node, Mapping):
        if "_recipe_" in node:
            return _resolve_recipe_args_node(node, root=root, path=path), True

        mapping_output: dict[str, Any] = {}
        has_recipe = False
        for key, value in node.items():
            resolved_child, child_has_recipe = _resolve_recipe_arguments(value, root=root, path=_child_path(path, key))
            mapping_output[key] = resolved_child
            if child_has_recipe:
                has_recipe = True
        return mapping_output, has_recipe

    if isinstance(node, list):
        sequence_output: list[Any] = []
        has_recipe = False
        for index, value in enumerate(node):
            resolved_child, child_has_recipe = _resolve_recipe_arguments(value, root=root, path=_child_path(path, index))
            sequence_output.append(resolved_child)
            has_recipe = has_recipe or child_has_recipe
        return sequence_output, has_recipe

    if isinstance(node, tuple):
        tuple_output: list[Any] = []
        has_recipe = False
        for index, value in enumerate(node):
            resolved_child, child_has_recipe = _resolve_recipe_arguments(value, root=root, path=_child_path(path, index))
            tuple_output.append(resolved_child)
            has_recipe = has_recipe or child_has_recipe
        return tuple_output, has_recipe

    return node, False


def _resolve_recipe_args_node(node: Mapping[str, Any], *, root: Mapping[str, Any], path: str) -> dict[str, Any]:
    recipe_name = node.get("_recipe_")
    if not isinstance(recipe_name, str):
        raise ConfigInterpolationError(f"_recipe_ must be a string at {path}")
    if recipe_name == "":
        raise ConfigInterpolationError(f"_recipe_ must be a non-empty string at {path}")

    _validate_recipe_reserved_keys(node, path=path)
    _reject_nested_recipe(node, path=path)

    output: dict[str, Any] = {"_recipe_": recipe_name}
    for key, value in node.items():
        if key == "_recipe_":
            continue
        output[key] = _resolve_recipe_argument_value(value, root=root, path=_child_path(path, key))
    return output


def _resolve_recipe_argument_value(value: Any, *, root: Mapping[str, Any], path: str) -> Any:
    if isinstance(value, str):
        return _resolve_string(value, root=root, path=path)
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, child in value.items():
            output[key] = _resolve_recipe_argument_value(child, root=root, path=_child_path(path, key))
        return output
    if isinstance(value, list):
        return [_resolve_recipe_argument_value(child, root=root, path=_child_path(path, index)) for index, child in enumerate(value)]
    if isinstance(value, tuple):
        return [_resolve_recipe_argument_value(child, root=root, path=_child_path(path, index)) for index, child in enumerate(value)]
    return value


def _resolve_string(value: str, *, root: Mapping[str, Any], path: str) -> Any:
    matches = list(_INTERPOLATION_RE.finditer(value))
    if not matches:
        return value

    def replacement(match: re.Match[str]) -> str:
        token = match.group(1)
        if ":" in token:
            return match.group(0)

        resolved = _lookup_interpolation_token(token, root=root, path=path)
        return str(_to_plain_output(resolved))

    if len(matches) == 1 and matches[0].span() == (0, len(value)):
        token = matches[0].group(1)
        if ":" in token:
            return value
        return _to_plain_output(_lookup_interpolation_token(token, root=root, path=path))

    output = value
    for match in reversed(matches):
        replacement_value = replacement(match)
        output = output[: match.start()] + replacement_value + output[match.end() :]
    return output


def _to_plain_output(value: Any) -> Any:
    return to_plain_data(value, path="$")


def _lookup_interpolation_token(token: str, *, root: Mapping[str, Any], path: str) -> Any:
    token = token.strip()
    current: Any = root

    for segment in token.split("."):
        if not segment:
            raise ConfigInterpolationError(f"Invalid interpolation token {token!r} at {path}")

        if segment.startswith("["):
            raise ConfigInterpolationError(f"Interpolation token {token!r} must start with a mapping key at {path}")

        match = _SEGMENT_RE.fullmatch(segment)
        if not match:
            raise ConfigInterpolationError(f"Invalid interpolation path segment {segment!r} in {token!r} at {path}")

        name = match.group("name")
        if not isinstance(current, Mapping):
            raise ConfigInterpolationError(f"Cannot resolve interpolation token {token!r} at {path}: {name!r} is not a mapping")
        if name not in current:
            raise ConfigInterpolationError(f"Interpolation token {token!r} at {path} is unresolved")

        current = current[name]
        for index_text in re.findall(r"\[([0-9]+)\]", match.group("indices")):
            index = int(index_text)
            if not isinstance(current, list):
                raise ConfigInterpolationError(f"Cannot apply index [{index}] for {token!r} at {path}")
            if index < 0 or index >= len(current):
                raise ConfigInterpolationError(f"Interpolation index [{index}] out of range for {token!r} at {path}")
            current = current[index]

    return current


def _expand_node(node: Any, *, catalog: RecipeCatalog, path: str) -> tuple[PlainData, tuple[RecipeManifestRecord, ...]]:
    if isinstance(node, dict):
        if "_recipe_" in node:
            return _expand_recipe_node(node, catalog=catalog, path=path)

        manifest: list[RecipeManifestRecord] = []
        mapping_output: dict[str, PlainData] = {}
        for key, child in node.items():
            expanded_child, child_manifest = _expand_node(child, catalog=catalog, path=_child_path(path, key))
            mapping_output[key] = expanded_child
            manifest.extend(child_manifest)
        return mapping_output, tuple(manifest)

    if isinstance(node, list):
        manifest: list[RecipeManifestRecord] = []
        sequence_output: list[PlainData] = []
        for index, child in enumerate(node):
            expanded_child, child_manifest = _expand_node(child, catalog=catalog, path=_child_path(path, index))
            sequence_output.append(expanded_child)
            manifest.extend(child_manifest)
        return sequence_output, tuple(manifest)

    return node, ()


def _expand_recipe_node(
    node: Mapping[str, Any],
    *,
    catalog: RecipeCatalog,
    path: str,
) -> tuple[dict[str, PlainData], tuple[RecipeManifestRecord, ...]]:
    if not isinstance(node.get("_recipe_"), str):
        raise RecipeExpansionError(
            f"Recipe name must be a string at {path}",
            context=_recipe_context(
                code="invalid_recipe_name",
                path=path,
                stage="recipe_expansion",
                expected="non-empty string",
                actual=type(node.get("_recipe_")).__name__,
                directive="_recipe_",
            ),
        )

    name = str(node["_recipe_"])
    if not name:
        raise RecipeExpansionError(
            f"Recipe name must be a non-empty string at {path}",
            context=_recipe_context(
                code="invalid_recipe_name",
                path=path,
                stage="recipe_expansion",
                expected="non-empty string",
                actual="empty string",
                directive="_recipe_",
            ),
        )

    _validate_recipe_reserved_keys(node, path=path)
    _reject_nested_recipe(node, path=path)

    impl = catalog.get(name)
    arguments: dict[str, PlainData] = {
        key: to_plain_data(value, path=_child_path(path, key)) for key, value in node.items() if key != "_recipe_"
    }
    expanded = _run_recipe(implementation=impl, name=name, arguments=arguments, path=path)

    try:
        expanded_plain = to_plain_data(expanded, path=path)
    except PlainDataError as exc:
        raise InvalidRecipeOutputError(
            f"Recipe {name!r} at {path} returned non-plain output",
            context=_recipe_context(
                code="recipe_output_non_plain",
                path=path,
                stage="recipe_expansion",
                expected="plain-data mapping",
                actual=type(expanded).__name__,
                details={"recipe_name": name},
            ),
        ) from exc
    if not isinstance(expanded_plain, dict):
        raise InvalidRecipeOutputError(
            f"Recipe {name!r} at {path} must return a mapping",
            context=_recipe_context(
                code="recipe_output_not_mapping",
                path=path,
                stage="recipe_expansion",
                expected="mapping",
                actual=type(expanded_plain).__name__,
                details={"recipe_name": name},
            ),
        )

    expanded_output, nested_manifest = _expand_node(expanded_plain, catalog=catalog, path=path)
    _reject_resolver_shape_dependency(expanded_output, path=path, recipe=name)
    if not isinstance(expanded_output, dict):
        raise InvalidRecipeOutputError(
            f"Expanded recipe output for {name!r} at {path} must remain mapping",
            context=_recipe_context(
                code="recipe_expanded_output_not_mapping",
                path=path,
                stage="recipe_expansion",
                expected="mapping",
                actual=type(expanded_output).__name__,
                details={"recipe_name": name},
            ),
        )

    manifest = RecipeManifestRecord.for_expansion(
        path=path,
        name=name,
        recipe=impl,
        arguments=arguments,
        expanded=expanded_output,
    )
    return expanded_output, (manifest, *nested_manifest)


def _reject_resolver_shape_dependency(value: Any, *, path: str, recipe: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and _RESOLVER_IN_KEY_RE.search(key):
                raise InvalidRecipeOutputError(
                    f"Recipe {recipe!r} at {path} returned resolver-shaped output key {key!r}",
                    context=_recipe_context(
                        code="recipe_output_resolver_shaped_key",
                        path=path,
                        stage="recipe_expansion",
                        directive="_recipe_",
                        details={"recipe_name": recipe, "output_key": key},
                    ),
                )
            _reject_resolver_shape_dependency(child, path=_child_path(path, key), recipe=recipe)
        return

    if isinstance(value, list):
        for index, child in enumerate(value):
            _reject_resolver_shape_dependency(child, path=_child_path(path, index), recipe=recipe)
        return

    if isinstance(value, tuple):
        for index, child in enumerate(value):
            _reject_resolver_shape_dependency(child, path=_child_path(path, index), recipe=recipe)


def _run_recipe(
    *,
    implementation: RecipeImplementation,
    name: str,
    arguments: Mapping[str, Any],
    path: str,
) -> Mapping[str, Any]:
    try:
        result = implementation(**arguments)
    except Exception as exc:  # noqa: BLE001
        raise RecipeExpansionError(
            f"Failed to expand recipe {name!r} at {path}",
            context=_recipe_context(
                code="recipe_execution_failed",
                path=path,
                stage="recipe_expansion",
                details={"recipe_name": name, "exception_type": type(exc).__name__},
            ),
        ) from exc

    if isinstance(result, Mapping):
        return dict(result)

    if isinstance(result, (Recipe, ConfigRecipe)):
        return _expand_recipe_object(result, name=name, path=path)

    expand = getattr(result, "expand", None)
    if callable(expand):
        try:
            output = expand()
        except Exception as exc:  # noqa: BLE001
            raise RecipeExpansionError(
                f"Failed to expand recipe {name!r} at {path}",
                context=_recipe_context(
                    code="recipe_object_expand_failed",
                    path=path,
                    stage="recipe_expansion",
                    details={"recipe_name": name, "exception_type": type(exc).__name__},
                ),
            ) from exc
        if not isinstance(output, Mapping):
            raise InvalidRecipeOutputError(
                f"Recipe {name!r} at {path} expand() must return a mapping",
                context=_recipe_context(
                    code="recipe_expand_output_not_mapping",
                    path=path,
                    stage="recipe_expansion",
                    expected="mapping",
                    actual=type(output).__name__,
                    details={"recipe_name": name},
                ),
            )
        return dict(output)

    raise InvalidRecipeOutputError(
        f"Recipe implementation {name!r} at {path} returned invalid expansion type {type(result)!r}",
        context=_recipe_context(
            code="invalid_recipe_expansion_type",
            path=path,
            stage="recipe_expansion",
            expected="mapping or expandable recipe object",
            actual=type(result).__name__,
            details={"recipe_name": name},
        ),
    )


def _expand_recipe_object(recipe: Recipe | ConfigRecipe, *, name: str, path: str) -> Mapping[str, Any]:
    output = recipe.expand()
    if not isinstance(output, Mapping):
        raise InvalidRecipeOutputError(
            f"Recipe {name!r} at {path} expand() must return a mapping",
            context=_recipe_context(
                code="recipe_expand_output_not_mapping",
                path=path,
                stage="recipe_expansion",
                expected="mapping",
                actual=type(output).__name__,
                details={"recipe_name": name},
            ),
        )
    return dict(output)


def _validate_recipe_reserved_keys(block: Mapping[str, Any], *, path: str) -> None:
    for key in block:
        if key == "_recipe_":
            continue
        if key in _RESERVED_KEYS:
            raise ReservedConfigKeyError(
                f"Reserved key {key!r} is not allowed in recipe blocks at {path}",
                context=_recipe_context(
                    code="reserved_recipe_key",
                    path=path,
                    stage="recipe_expansion",
                    directive=key,
                    details={"reserved_key": key},
                ),
            )


def _reject_nested_recipe(value: Mapping[str, Any], *, path: str) -> None:
    for key, child in value.items():
        if key == "_recipe_":
            continue
        _reject_nested_recipe_value(child, path=_child_path(path, key))


def _reject_nested_recipe_value(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        if "_recipe_" in value:
            raise RecipeExpansionError(
                f"Nested _recipe_ blocks are only allowed in recipe output at {path}",
                context=_recipe_context(
                    code="nested_recipe_block",
                    path=path,
                    stage="recipe_expansion",
                    directive="_recipe_",
                ),
            )
        for key, child in value.items():
            _reject_nested_recipe_value(child, path=_child_path(path, key))
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _reject_nested_recipe_value(child, path=_child_path(path, index))
    if isinstance(value, tuple):
        for index, child in enumerate(value):
            _reject_nested_recipe_value(child, path=_child_path(path, index))


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


def _recipe_context(
    *,
    code: str,
    path: str,
    stage: str,
    expected: object | None = None,
    actual: object | None = None,
    directive: str | None = None,
    details: dict[str, object] | None = None,
) -> ConfigErrorContext:
    return ConfigErrorContext(
        code=code,
        source_kind="recipe",
        source_order=0,
        source_path="<recipe>",
        config_path=path,
        expected=to_plain_data(expected) if expected is not None else None,
        actual=to_plain_data(actual) if actual is not None else None,
        directive=directive,
        remediation=_recipe_remediation(code),
        details=cast(dict[str, PlainData], to_plain_data({"stage": stage, **(details or {})})),
    )


def _recipe_remediation(code: str) -> str | None:
    if code == "reserved_recipe_key":
        return "Remove target/instantiation directives from recipe argument blocks."
    if code == "nested_recipe_block":
        return "Return nested recipes from the trusted recipe implementation instead of authoring them as arguments."
    if code.endswith("not_mapping") or code in {"recipe_output_not_mapping", "recipe_expand_output_not_mapping"}:
        return "Return a mapping from recipe expansion."
    if code == "recipe_output_resolver_shaped_key":
        return "Use stable literal output keys; resolver expressions may remain in values only."
    return None
