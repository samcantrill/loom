"""Recipe manifest records for deterministic composition provenance."""

from __future__ import annotations

from dataclasses import dataclass

from loom import __version__
from loom.fingerprints import hash_mapping
from loom.serialization import PlainData, ensure_plain_data

from .base import RecipeImplementation


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
            "arguments": self.arguments,
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
        arguments: dict[str, PlainData],
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


def _normalize_arguments(arguments: dict[str, object]) -> dict[str, PlainData]:
    return ensure_plain_data(arguments, path="recipe_arguments")


def _recipe_target(recipe: RecipeImplementation) -> str:
    return f"{getattr(recipe, '__module__', '<unknown>')}:{getattr(recipe, '__qualname__', getattr(recipe, '__name__', 'unknown'))}"


__all__ = ["RecipeManifestRecord"]
