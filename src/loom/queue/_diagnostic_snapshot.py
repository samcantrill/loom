"""Annotate existing diagnostic structure without expanding private execution data."""

from collections.abc import Iterator, Mapping
from typing import cast

from loom.serialization import PlainData


def diagnostic_stages(snapshot: Mapping[str, PlainData] | None) -> Iterator[tuple[int, dict[str, PlainData]]]:
    """Yield literal stage mappings, retaining their original list positions.

    Weave diagnostic views can preserve interpolation strings or redact entire
    mappings. Those values must remain opaque, including inside the stage list.
    """
    pipeline = snapshot.get("pipeline") if snapshot is not None else None
    if not isinstance(pipeline, dict):
        return
    stages = pipeline.get("stages")
    if not isinstance(stages, list):
        return
    for index, stage in enumerate(stages):
        if isinstance(stage, dict):
            yield index, cast(dict[str, PlainData], stage)


def annotate_mapping(stage: dict[str, PlainData], field: str, additions: Mapping[str, PlainData]) -> None:
    """Add binding facts only when the diagnostic field is absent or literal."""
    value = stage.get(field, {})
    if isinstance(value, dict):
        stage[field] = {**value, **additions}
