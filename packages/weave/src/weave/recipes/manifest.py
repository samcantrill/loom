"""Recipe manifest records for deterministic composition provenance."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from weave.__version__ import __version__
from ..digests import hash_mapping
from ..plain import PlainData, ensure_plain_data

from .base import RecipeImplementation
from ..redaction import redact_secret_like_value


@dataclass(frozen=True, slots=True)
class RecipeManifestRecord:
    path: str
    name: str
    target: str
    arguments: dict[str, PlainData]
    expanded_hash: str
    expanded_path: str
    loom_version: str

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "path": self.path,
            "name": self.name,
            "target": self.target,
            "arguments": _redact_arguments(self.arguments),
            "expanded_hash": self.expanded_hash,
            "expanded_path": self.expanded_path,
            "loom_version": self.loom_version,
        }

    @classmethod
    def for_expansion(
        cls,
        *,
        path: str,
        name: str,
        recipe: RecipeImplementation,
        arguments: Mapping[str, PlainData],
        expanded: dict[str, PlainData],
    ) -> "RecipeManifestRecord":
        expanded_hash = hash_mapping(expanded)
        return cls(
            path=path,
            name=name,
            target=_recipe_target(recipe),
            arguments=_normalize_arguments(arguments),
            expanded_hash=expanded_hash,
            expanded_path=path,
            loom_version=__version__,
        )


def _normalize_arguments(arguments: Mapping[str, object]) -> dict[str, PlainData]:
    plain = ensure_plain_data(dict(arguments), path="recipe_arguments")
    if not isinstance(plain, dict):
        raise TypeError("recipe arguments must normalize to a mapping")
    return plain


def _redact_arguments(arguments: Mapping[str, PlainData]) -> dict[str, PlainData]:
    return {key: redact_secret_like_value(key, value) for key, value in arguments.items()}


def _recipe_target(recipe: RecipeImplementation) -> str:
    return f"{getattr(recipe, '__module__', '<unknown>')}:{getattr(recipe, '__qualname__', getattr(recipe, '__name__', 'unknown'))}"


__all__ = ["RecipeManifestRecord"]
