"""Integration checks for raw source snapshot opt-in behavior."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from loom.config import RecipeCatalog, compose_config
from tests.support.config_samples import argument_recipe


def test_integration_default_compose_reports_raw_snapshot_availability_metadata(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  value: 1\n",
        encoding="utf-8",
    )
    overlay.write_text("pipeline:\n  value: 2\n", encoding="utf-8")

    composed = compose_config(base, overlays=(overlay,))

    assert composed.raw_source_snapshots.enabled is False
    assert composed.raw_source_snapshots.payloads == ()

    manifest_metadata = cast(dict[str, Any], composed.manifest.to_dict()["metadata"])
    provenance_metadata = cast(dict[str, Any], composed.provenance.to_dict()["metadata"])
    manifest_refs = cast(list[dict[str, Any]], manifest_metadata["raw_source_snapshot_references"])
    provenance_refs = cast(list[dict[str, Any]], provenance_metadata["raw_source_snapshot_references"])
    assert manifest_refs == provenance_refs
    assert all(reference["availability"] == "disabled" for reference in manifest_refs)
    assert all(reference["reason"] == "not_requested" for reference in manifest_refs)
    assert all(reference["payload_id"] is None for reference in manifest_refs)
    assert all("content" not in reference for reference in manifest_refs)

    source_artifact_payload = composed.manifest.metadata["source_reference_count"]
    assert source_artifact_payload == len(composed.source_artifacts)


def test_integration_compose_raw_snapshot_opt_in_includes_reconstructable_payloads(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    included = tmp_path / "includes.yaml"

    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  model:\n"
        "    _include_: includes.yaml\n",
        encoding="utf-8",
    )
    shared = "name: shared\nvalue: 1\n"
    overlay.write_text(shared, encoding="utf-8")
    included.write_text(shared, encoding="utf-8")

    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  model:\n"
        "    _include_: includes.yaml\n",
        encoding="utf-8",
    )

    composed = compose_config(base, overlays=(overlay,), include_raw_source_snapshots=True)

    assert composed.raw_source_snapshots.enabled is True
    assert len(composed.source_artifacts) == 3

    references = composed.raw_source_snapshots.references
    reference_ids_by_kind = {
        reference.kind: reference.payload_id for reference in references if reference.payload_id is not None
    }
    assert reference_ids_by_kind["overlay"] == reference_ids_by_kind["include"]
    assert len(composed.raw_source_snapshots.payloads) == 2

    manifest_metadata = cast(dict[str, Any], composed.manifest.to_dict()["metadata"])
    manifest_refs = cast(list[dict[str, Any]], manifest_metadata["raw_source_snapshot_references"])
    assert any(reference["availability"] == "available" for reference in manifest_refs)
    assert all(reference["payload_id"] is not None for reference in manifest_refs[:2])

    available_payloads = tuple(
        payload for payload in composed.raw_source_snapshots.payloads if payload.payload_id == reference_ids_by_kind["overlay"]
    )
    assert len(available_payloads) == 1
    assert available_payloads[0].encoding == "utf-8"
    assert available_payloads[0].size_bytes == len(shared)


def test_integration_user_include_replacement_snapshots_nested_include_sources(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    include_dir = tmp_path / "includes"
    include_dir.mkdir()
    original = include_dir / "original.yaml"
    replacement = include_dir / "replacement.yaml"
    leaf = include_dir / "leaf.yaml"

    base_text = (
        "name: base\n"
        "pipeline:\n"
        "  model:\n"
        "    _include_: ./includes/original.yaml\n"
    )
    replacement_text = "component:\n  _include_: leaf.yaml\n"
    leaf_text = "leaf_value: replacement-leaf\n"
    base.write_text(base_text, encoding="utf-8")
    original.write_text("component:\n  old: true\n", encoding="utf-8")
    replacement.write_text(replacement_text, encoding="utf-8")
    leaf.write_text(leaf_text, encoding="utf-8")

    composed = compose_config(
        base,
        overrides=("pipeline.model._include_=./includes/replacement.yaml",),
        include_raw_source_snapshots=True,
    )

    assert composed.resolved["pipeline"] == {
        "model": {"component": {"leaf_value": "replacement-leaf"}}
    }
    assert composed.raw_source_snapshots.enabled is True

    source_paths = {record.path for record in composed.source_artifacts}
    assert source_paths == {
        str(base.resolve()),
        str(replacement.resolve()),
        str(leaf.resolve()),
    }

    payloads_by_id = {
        payload.payload_id: payload for payload in composed.raw_source_snapshots.payloads
    }
    references_by_path = {
        reference.path: reference for reference in composed.raw_source_snapshots.references
    }
    assert set(references_by_path) == source_paths
    for path, expected_content in {
        str(base.resolve()): base_text,
        str(replacement.resolve()): replacement_text,
        str(leaf.resolve()): leaf_text,
    }.items():
        reference = references_by_path[path]
        assert reference.availability == "available"
        assert reference.payload_id is not None
        assert payloads_by_id[reference.payload_id].content == expected_content

    include_artifacts = [
        record for record in composed.source_artifacts if record.kind == "include"
    ]
    assert [record.path for record in include_artifacts] == [
        str(replacement.resolve()),
        str(leaf.resolve()),
    ]
    nested_metadata = cast(dict[str, Any], include_artifacts[1].metadata)
    assert list(cast(tuple[str, ...], nested_metadata["include_site_path"])) == [
        "pipeline",
        "model",
        "component",
        "_include_",
    ]
    assert list(cast(tuple[str, ...], nested_metadata["source_include_site_path"])) == [
        "component",
        "_include_",
    ]

    manifest_metadata = cast(dict[str, Any], composed.manifest.to_dict()["metadata"])
    provenance_metadata = cast(dict[str, Any], composed.provenance.to_dict()["metadata"])
    manifest_refs = cast(list[dict[str, Any]], manifest_metadata["raw_source_snapshot_references"])
    provenance_refs = cast(list[dict[str, Any]], provenance_metadata["raw_source_snapshot_references"])
    assert {reference["path"] for reference in manifest_refs} == source_paths
    assert {reference["path"] for reference in provenance_refs} == source_paths
    assert all(reference["availability"] == "available" for reference in manifest_refs)
    assert all("content" not in reference for reference in manifest_refs)


def test_integration_compose_raw_snapshot_unavailable_recipe_records_are_marked(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    catalog = RecipeCatalog()
    catalog.register("arg", argument_recipe)

    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  _recipe_: arg\n"
        "  value: one\n",
        encoding="utf-8",
    )

    composed = compose_config(base, recipe_catalog=catalog, include_raw_source_snapshots=True)

    recipe_references = [
        reference for reference in composed.raw_source_snapshots.references if reference.kind == "recipe"
    ]
    assert len(recipe_references) == 1
    assert recipe_references[0].availability == "unavailable"
    assert recipe_references[0].reason == "unsupported_source_kind"
    assert recipe_references[0].payload_id is None


def test_integration_raw_snapshot_fingerprint_excludes_raw_payloads(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    base = tmp_path / "base.yaml"
    base.write_text("name: base\npipeline:\n  value: ${oc.env:PHASE15_ROOT}/value\n", encoding="utf-8")
    monkeypatch.setenv("PHASE15_ROOT", "root")

    composed_default = compose_config(base)
    composed_with_snapshots = compose_config(base, include_raw_source_snapshots=True)

    assert composed_default.fingerprint == composed_with_snapshots.fingerprint
    assert composed_with_snapshots.fingerprint_records[0].metadata["raw_source_bytes_included"] is False
    assert composed_with_snapshots.fingerprint_records[0].metadata["resolver_outputs_included"] is False
    artifact_payload = composed_with_snapshots.fingerprint_records[0].metadata
    assert "raw_source_snapshot_references" not in artifact_payload
