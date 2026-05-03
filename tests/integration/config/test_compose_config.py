"""Integration checks for public compose_config behavior."""

from pathlib import Path

import pytest

from loom.config import compose_config
from loom.config.errors import UnsupportedRecipeError


pytestmark = pytest.mark.integration


def test_public_composition_with_overlays_and_overrides(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    overlay2 = tmp_path / "overlay2.yaml"

    base.write_text("name: base\npipeline:\n  root: ${paths.root}\n  paths:\n    root: /tmp\n", encoding="utf-8")
    overlay.write_text("pipeline:\n  stage: overlay\n", encoding="utf-8")
    overlay2.write_text("pipeline:\n  nested:\n    value: ${pipeline.stage}\n", encoding="utf-8")

    composed = compose_config(
        config_path=base,
        overlays=(overlay, overlay2),
        overrides=("pipeline.stage=override", "+pipeline.secret_token=sauce"),
    )

    assert composed.resolved["pipeline"]["stage"] == "override"
    assert composed.resolved["pipeline"]["nested"]["value"] == "overlay"
    assert composed.redacted["pipeline"]["secret_token"] == "***REDACTED***"


def test_public_compose_rejects_recipes(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text("name: base\npipeline:\n  steps: []\n_recipe_:\n  - bad\n", encoding="utf-8")
    with pytest.raises(UnsupportedRecipeError):
        compose_config(base)


def test_public_fingerprints_change_with_overlay_order(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    overlay_a = tmp_path / "a.yaml"
    overlay_b = tmp_path / "b.yaml"

    base.write_text("name: base\npipeline:\n  value: one\n", encoding="utf-8")
    overlay_a.write_text("pipeline:\n  a: 1\n", encoding="utf-8")
    overlay_b.write_text("pipeline:\n  a: 2\n", encoding="utf-8")

    first = compose_config(base, overlays=(overlay_a, overlay_b))
    second = compose_config(base, overlays=(overlay_b, overlay_a))

    assert first.fingerprint != second.fingerprint
