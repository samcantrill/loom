"""Compose multiple config overlays and replace one mapping."""

from __future__ import annotations

from pathlib import Path
from pprint import pprint

from loom.config import compose_config


HERE = Path(__file__).resolve().parent


def _contains_replace_marker(value: object) -> bool:
    if isinstance(value, dict):
        return "_replace_" in value or any(
            _contains_replace_marker(child) for child in value.values()
        )
    if isinstance(value, list):
        return any(_contains_replace_marker(child) for child in value)
    return False


def main() -> None:
    composed = compose_config(
        HERE / "base.yaml",
        overlays=(
            HERE / "overlay-one.yaml",
            HERE / "overlay-two.yaml",
        ),
    )

    workflow = composed.resolved["workflow"]
    assert isinstance(workflow, dict)
    assert workflow["retry_policy"] == {"attempts": 2, "delay_seconds": 10}
    assert workflow["resources"] == {"cpu": 4, "memory": "8Gi"}
    assert workflow["labels"] == {
        "owner": "platform",
        "lifecycle": "review",
        "source": "overlay-two",
    }
    assert not _contains_replace_marker(composed.resolved)

    print("resolved workflow:")
    pprint(workflow, sort_dicts=True)
    print("source order:")
    pprint(
        [
            {
                "kind": source.kind,
                "order": source.order,
                "path": Path(source.path).name,
            }
            for source in composed.provenance.sources
        ],
        sort_dicts=True,
    )


if __name__ == "__main__":
    main()
