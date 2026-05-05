"""Integration matrix for raw source snapshots across include replacement."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from loom.config import compose_config


def test_compose_raw_snapshots_track_replaced_and_added_includes(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    include_dir = tmp_path / "includes"
    include_dir.mkdir()
    original_include = include_dir / "original-model.yaml"
    replacement_include = include_dir / "replacement-model.yaml"
    added_include = include_dir / "dataset.yaml"

    base_text = (
        "name: snapshot-matrix\n"
        "pipeline:\n"
        "  model:\n"
        "    _include_: ./includes/original-model.yaml\n"
        "    local: base\n"
    )
    overlay_text = (
        "pipeline:\n"
        "  model:\n"
        "    _replace_: true\n"
        "    _include_: ./includes/replacement-model.yaml\n"
        "    local: overlay\n"
        "  dataset:\n"
        "    _include_: ./includes/dataset.yaml\n"
    )
    original_include_text = "kind: original\n"
    replacement_include_text = "kind: replacement\n"
    added_include_text = "kind: added\nrows: 100\n"

    base.write_text(base_text, encoding="utf-8")
    overlay.write_text(overlay_text, encoding="utf-8")
    original_include.write_text(original_include_text, encoding="utf-8")
    replacement_include.write_text(replacement_include_text, encoding="utf-8")
    added_include.write_text(added_include_text, encoding="utf-8")

    composed = compose_config(
        base,
        overlays=(overlay,),
        include_raw_source_snapshots=True,
    )

    assert composed.resolved["pipeline"] == {
        "model": {"kind": "replacement", "local": "overlay"},
        "dataset": {"kind": "added", "rows": 100},
    }
    assert composed.raw_source_snapshots.enabled is True

    expected_sources = {
        str(base.resolve()): ("base", base_text),
        str(overlay.resolve()): ("overlay", overlay_text),
        str(replacement_include.resolve()): ("include", replacement_include_text),
        str(added_include.resolve()): ("include", added_include_text),
    }
    original_include_path = str(original_include.resolve())

    artifacts_by_path = {artifact.path: artifact for artifact in composed.source_artifacts}
    assert set(artifacts_by_path) == set(expected_sources)
    assert original_include_path not in artifacts_by_path
    for path, (kind, _content) in expected_sources.items():
        assert artifacts_by_path[path].kind == kind

    payloads_by_id = {
        payload.payload_id: payload for payload in composed.raw_source_snapshots.payloads
    }
    references_by_path = {
        reference.path: reference for reference in composed.raw_source_snapshots.references
    }
    assert set(references_by_path) == set(expected_sources)
    assert original_include_path not in references_by_path

    for path, (_kind, expected_content) in expected_sources.items():
        reference = references_by_path[path]
        assert reference.availability == "available"
        assert reference.payload_id is not None
        payload = payloads_by_id[reference.payload_id]
        assert payload.encoding == "utf-8"
        assert payload.content == expected_content
        assert payload.size_bytes == len(expected_content)

    manifest_metadata = cast(dict[str, Any], composed.manifest.to_dict()["metadata"])
    manifest_refs = cast(list[dict[str, Any]], manifest_metadata["raw_source_snapshot_references"])
    assert {reference["path"] for reference in manifest_refs} == set(expected_sources)
    assert all(reference["availability"] == "available" for reference in manifest_refs)
    assert all("content" not in reference for reference in manifest_refs)

    fingerprint_metadata = composed.fingerprint_records[0].metadata
    assert fingerprint_metadata["raw_source_bytes_included"] is False
    assert "raw_source_snapshot_references" not in fingerprint_metadata
