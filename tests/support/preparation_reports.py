"""Read actual canonical preparation output through its supported SDK boundary."""

from pathlib import Path
from typing import Any, cast

from loom.artifacts import ArtifactRef
from loom.pipeline.stores import LocalArtifactStore
from loom.preparation import load_preparation_report


def load_report(root: str | Path, reference: ArtifactRef) -> dict[str, Any]:
    store = LocalArtifactStore(root)
    return cast(
        dict[str, Any], load_preparation_report(reference, store.local_path(reference))
    )
