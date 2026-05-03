"""Recipe expansion orchestration."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from loom.serialization import PlainData, to_plain_data
from loom.serialization.errors import PlainDataError
from loom.config.errors import ConfigInterpolationError, InvalidRecipeOutputError, RecipeExpansionError, ReservedConfigKeyError

from .base import ConfigRecipe, Recipe, RecipeImplementation
from .catalog import RecipeCatalog
from .manifest import RecipeManifestRecord

_RESERVED_KEYS = frozenset({"_target_", "_args_", "_partial_", "_inject_", "_recipe_"})
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SEGMENT_RE = re.compile(r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<indices>(?:\[[0-9]+\])*)")
_INTERPOLATION_RE = re.compile(r"\$\{([^{}]+)\}")


def resolve_recipe_argument_interpolation(
    config: Mapping[str, PlainData],
    *,
    path: str = "$",
) -> dict[str, PlainData]:
    """Resolve interpolation only inside recipe argument values."""

    root = to_plain_data(config, path=path)
    resolved, _ = _resolve_recipe_arguments(root, root=root, path=path)
    if not isinstance(resolved, dict):
        raise ConfigInterpolationError(f"Recipe argument resolution root must be a mapping at {path}")
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
    return expanded, tuple(item.to_dict() for item in manifest)


def _resolve_recipe_arguments(node: Any, *, root: Mapping[str, Any], path: str) -> tuple[Any, bool]:
    if isinstance(node, Mapping):
        if "_recipe_" in node:
            return _resolve_recipe_args_node(node, root=root, path=path), True

        output: dict[str, Any] = {}
        has_recipe = False
        for key, value in node.items():
            resolved_child, child_has_recipe = _resolve_recipe_arguments(value, root=root, path=_child_path(path, key))
            output[key] = resolved_child
            if child_has_recipe:
                has_recipe = True
        return output, has_recipe

    if isinstance(node, list):
        output: list[Any] = []
        has_recipe = False
        for index, value in enumerate(node):
            resolved_child, child_has_recipe = _resolve_recipe_arguments(value, root=root, path=_child_path(path, index))
            output.append(resolved_child)
            has_recipe = has_recipe or child_has_recipe
        return output, has_recipe

    if isinstance(node, tuple):
        output: list[Any] = []
        has_recipe = False
        for index, value in enumerate(node):
            resolved_child, child_has_recipe = _resolve_recipe_arguments(value, root=root, path=_child_path(path, index))
            output.append(resolved_child)
            has_recipe = has_recipe or child_has_recipe
        return output, has_recipe

    return node, False


def _resolve_recipe_args_node(node: Mapping[str, Any], *, root: Mapping[str, Any], path: str) -> dict[str, Any]:
    recipe_name = node.get("_recipe_")
    if not isinstance(recipe_name, str):
        raise ConfigInterpolationError(f"_recipe_ must be a string at {path}")
    if recipe_name == "":
        raise ConfigInterpolationError(f"_recipe_ must be a non-empty string at {path}")

    _validate_recipe_reserved_keys(node, path=path)

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

    if any(":" in match.group(1) for match in matches):
        raise ConfigInterpolationError(f"Resolver-style interpolation is not supported at {path}")

    def replacement(match: re.Match[str]) -> str:
        token = match.group(1)
        resolved = _lookup_interpolation_token(token, root=root, path=path)
        return str(_to_plain_output(resolved))

    if len(matches) == 1 and matches[0].span() == (0, len(value)):
        return _to_plain_output(_lookup_interpolation_token(matches[0].group(1), root=root, path=path))

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


def _expand_node(node: Any, *, catalog: RecipeCatalog, path: str) -> tuple[dict[str, PlainData], tuple[RecipeManifestRecord, ...]]:
    if isinstance(node, dict):
        if "_recipe_" in node:
            return _expand_recipe_node(node, catalog=catalog, path=path)

        manifest: list[RecipeManifestRecord] = []
        output: dict[str, PlainData] = {}
        for key, child in node.items():
            expanded_child, child_manifest = _expand_node(child, catalog=catalog, path=_child_path(path, key))
            output[key] = expanded_child
            manifest.extend(child_manifest)
        return output, tuple(manifest)

    if isinstance(node, list):
        manifest: list[RecipeManifestRecord] = []
        output: list[PlainData] = []
        for index, child in enumerate(node):
            expanded_child, child_manifest = _expand_node(child, catalog=catalog, path=_child_path(path, index))
            output.append(expanded_child)
            manifest.extend(child_manifest)
        return output, tuple(manifest)

    return node, ()


def _expand_recipe_node(
    node: Mapping[str, Any],
    *,
    catalog: RecipeCatalog,
    path: str,
) -> tuple[dict[str, PlainData], tuple[RecipeManifestRecord, ...]]:
    if not isinstance(node.get("_recipe_"), str):
        raise RecipeExpansionError(f"Recipe name must be a string at {path}")

    name = str(node["_recipe_"])
    if not name:
        raise RecipeExpansionError(f"Recipe name must be a non-empty string at {path}")

    _validate_recipe_reserved_keys(node, path=path)
    _reject_nested_recipe(node, path=path)

    impl = catalog.get(name)
    arguments = {key: value for key, value in node.items() if key != "_recipe_"}
    expanded = _run_recipe(implementation=impl, name=name, arguments=arguments, path=path)

    try:
        expanded_plain = to_plain_data(expanded, path=path)
    except PlainDataError as exc:
        raise InvalidRecipeOutputError(f"Recipe {name!r} at {path} returned non-plain output") from exc
    if not isinstance(expanded_plain, dict):
        raise InvalidRecipeOutputError(f"Recipe {name!r} at {path} must return a mapping")

    expanded_output, nested_manifest = _expand_node(expanded_plain, catalog=catalog, path=path)
    if not isinstance(expanded_output, dict):
        raise InvalidRecipeOutputError(f"Expanded recipe output for {name!r} at {path} must remain mapping")

    manifest = RecipeManifestRecord.for_expansion(
        path=path,
        name=name,
        recipe=impl,
        arguments=arguments,
        expanded=expanded_output,
    )
    return expanded_output, (manifest, *nested_manifest)


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
        raise RecipeExpansionError(f"Failed to expand recipe {name!r} at {path}") from exc

    if isinstance(result, Mapping):
        return dict(result)

    if isinstance(result, (Recipe, ConfigRecipe)):
        return _expand_recipe_object(result, name=name, path=path)

    expand = getattr(result, "expand", None)
    if callable(expand):
        try:
            output = expand()
        except Exception as exc:  # noqa: BLE001
            raise RecipeExpansionError(f"Failed to expand recipe {name!r} at {path}") from exc
        if not isinstance(output, Mapping):
            raise InvalidRecipeOutputError(f"Recipe {name!r} at {path} expand() must return a mapping")
        return dict(output)

    raise InvalidRecipeOutputError(f"Recipe implementation {name!r} at {path} returned invalid expansion type {type(result)!r}")


def _expand_recipe_object(recipe: Recipe | ConfigRecipe, *, name: str, path: str) -> Mapping[str, Any]:
    output = recipe.expand()
    if not isinstance(output, Mapping):
        raise InvalidRecipeOutputError(f"Recipe {name!r} at {path} expand() must return a mapping")
    return dict(output)


def _validate_recipe_reserved_keys(block: Mapping[str, Any], *, path: str) -> None:
    for key in block:
        if key == "_recipe_":
            continue
        if key in _RESERVED_KEYS:
            raise ReservedConfigKeyError(f"Reserved key {key!r} is not allowed in recipe blocks at {path}")


def _reject_nested_recipe(value: Mapping[str, Any], *, path: str) -> None:
    for key, child in value.items():
        if key == "_recipe_":
            continue
        _reject_nested_recipe_value(child, path=_child_path(path, key))


def _reject_nested_recipe_value(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        if "_recipe_" in value:
            raise RecipeExpansionError(f"Nested _recipe_ blocks are only allowed in recipe output at {path}")
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
