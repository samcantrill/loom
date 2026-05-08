"""Compose trusted YAML config and expand a registered recipe."""

from __future__ import annotations

from pathlib import Path
from pprint import pprint

from loom.config import RecipeCatalog, compose_config

from recipes import RetentionPolicy


HERE = Path(__file__).resolve().parent


def main() -> None:
    catalog = RecipeCatalog()
    catalog.register("retention_policy", RetentionPolicy)

    composed = compose_config(
        HERE / "base.yaml",
        overlays=(HERE / "overlay.yaml",),
        overrides=(
            "settings.retention_days=14",
            "+settings.mode=dry-run",
        ),
        recipe_catalog=catalog,
    )

    print("fingerprint:")
    print(f"  {composed.fingerprint}")
    print("resolved pipeline:")
    pprint(composed.resolved["pipeline"], sort_dicts=True)
    print("redacted settings:")
    pprint(composed.redacted["settings"], sort_dicts=True)
    print("recipe manifest:")
    pprint(composed.recipe_manifest, sort_dicts=True)


if __name__ == "__main__":
    main()

