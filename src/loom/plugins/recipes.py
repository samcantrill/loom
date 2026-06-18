"""Recipe plugin adapters."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Protocol, cast

from .entrypoints import LOOM_RECIPES_GROUP, PluginLoadResult, PluginRecord, load_entry_points

RecipeImplementation = Callable[..., object] | type[Any]


class RecipeCatalogLike(Protocol):
    """Structural catalog surface required by recipe plugin loading."""

    def register(
        self,
        name: str,
        recipe: RecipeImplementation,
        *,
        replace: bool = False,
    ) -> None: ...


def load_recipe_entry_points(
    records: Iterable[PluginRecord],
    catalog: RecipeCatalogLike,
    *,
    selected: Iterable[PluginRecord] | None = None,
    strict: bool = True,
    replace: bool = False,
) -> PluginLoadResult:
    """Load selected recipe entry points into a caller-supplied catalog."""

    return load_entry_points(
        records=_filter_records(records, LOOM_RECIPES_GROUP),
        selected=_filter_records(selected, LOOM_RECIPES_GROUP) if selected is not None else None,
        strict=strict,
        register=lambda record, value: catalog.register(
            name=record.name,
            recipe=cast(RecipeImplementation, value),
            replace=replace,
        ),
    )


def _filter_records(
    records: Iterable[PluginRecord] | None,
    group: str,
) -> tuple[PluginRecord, ...]:
    if records is None:
        return ()
    return tuple(record for record in records if record.group == group)


__all__ = [
    "RecipeCatalogLike",
    "load_recipe_entry_points",
]
