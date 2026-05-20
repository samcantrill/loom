"""Compose base and overlay YAML with ordinary overrides."""

from __future__ import annotations

from pathlib import Path
from pprint import pprint

from weave import compose_config


HERE = Path(__file__).resolve().parent


def main() -> None:
    composed = compose_config(
        HERE / "base.yaml",
        overlays=(HERE / "overlay.yaml",),
        overrides=(
            "settings.batch_size=8",
            "+settings.note=added-by-override",
            '+pipeline.tags=["composition","smoke"]',
        ),
    )

    print("resolved pipeline:")
    pprint(composed.resolved["pipeline"], sort_dicts=True)
    print("unresolved pipeline:")
    pprint(composed.unresolved["pipeline"], sort_dicts=True)
    print("redacted settings:")
    pprint(composed.redacted["settings"], sort_dicts=True)


if __name__ == "__main__":
    main()
