"""Integration coverage for multi-overlay replacement provenance."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

pytestmark = pytest.mark.optional_dependency

pytest.importorskip("yaml")
pytest.importorskip("omegaconf")
pytest.importorskip("pydantic")

from loom.config import compose_config  # noqa: E402
from loom.serialization import PlainData  # noqa: E402


def _assert_no_replace_markers(value: PlainData) -> None:
    if isinstance(value, dict):
        assert "_replace_" not in value
        for child in value.values():
            _assert_no_replace_markers(child)
        return

    if isinstance(value, list):
        for child in value:
            _assert_no_replace_markers(child)


def test_multi_overlay_replace_removes_marker_and_preserves_source_order(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    overlay_one = tmp_path / "overlay-one.yaml"
    overlay_two = tmp_path / "overlay-two.yaml"

    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  stage: base\n"
        "  retries: 1\n",
        encoding="utf-8",
    )
    overlay_one.write_text(
        "pipeline:\n"
        "  model:\n"
        "    family: introduced\n"
        "    params:\n"
        "      width: 128\n"
        "      stale: true\n"
        "  overlay_one_only: retained\n",
        encoding="utf-8",
    )
    overlay_two.write_text(
        "pipeline:\n"
        "  model:\n"
        "    _replace_: true\n"
        "    family: replacement\n"
        "    params:\n"
        "      width: 256\n"
        "      depth: 4\n",
        encoding="utf-8",
    )

    composed = compose_config(base, overlays=(overlay_one, overlay_two))

    assert composed.resolved == {
        "name": "base",
        "pipeline": {
            "stage": "base",
            "retries": 1,
            "model": {
                "family": "replacement",
                "params": {
                    "width": 256,
                    "depth": 4,
                },
            },
            "overlay_one_only": "retained",
        },
    }
    _assert_no_replace_markers(composed.resolved)
    _assert_no_replace_markers(composed.unresolved)
    _assert_no_replace_markers(composed.redacted)

    expected_sources = [
        ("base", str(base.resolve()), 0),
        ("overlay", str(overlay_one.resolve()), 1),
        ("overlay", str(overlay_two.resolve()), 2),
    ]
    assert [(source.kind, source.path, source.order) for source in composed.provenance.sources] == expected_sources
    assert [(artifact.kind, artifact.path, artifact.order) for artifact in composed.source_artifacts] == expected_sources

    source_fact_records = cast(dict[str, Any], composed.provenance.metadata["source_fact_records"])
    source_fact_sources = cast(list[dict[str, Any]], source_fact_records["sources"])
    assert [(source["kind"], source["path"], source["order"]) for source in source_fact_sources] == expected_sources

    source_artifact_references = cast(
        list[dict[str, Any]],
        composed.manifest.metadata["source_artifact_references"],
    )
    assert [
        (reference["kind"], reference["path"], reference["order"])
        for reference in source_artifact_references
    ] == expected_sources
