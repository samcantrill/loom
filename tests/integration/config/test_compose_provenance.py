"""Cross-feature integration checks for compose provenance and artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from loom.config import RecipeCatalog, compose_config, inspect_config_composition
from loom.config.redaction import REDACTION_MARKER
from loom.config.fingerprints import ARTIFACT_SAFE_FINGERPRINT_LABEL, ARTIFACT_SAFE_FINGERPRINT_POLICY
from tests.support.config_samples import argument_recipe


def test_public_compose_populates_source_artifact_records(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    included = tmp_path / "included.yaml"

    included.write_text("shared: from-include\n", encoding="utf-8")
    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  model:\n"
        "    _include_: included.yaml\n"
        "    local: from-base\n",
        encoding="utf-8",
    )
    overlay.write_text("pipeline:\n  model:\n    local: from-overlay\n", encoding="utf-8")

    composed = compose_config(base, overlays=(overlay,))
    assert composed.source_artifacts
    assert len(composed.source_artifacts) == 3
    assert [artifact.kind for artifact in composed.source_artifacts] == ["base", "overlay", "include"]

    source_artifact_references = cast(
        list[dict[str, Any]],
        cast(dict[str, Any], composed.manifest.to_dict()["metadata"])["source_artifact_references"],
    )
    assert len(source_artifact_references) == len(composed.source_artifacts)
    for artifact, reference in zip(composed.source_artifacts, source_artifact_references, strict=True):
        assert reference["kind"] == artifact.kind
        assert reference["path"] == artifact.path
        assert reference["order"] == artifact.order


def test_public_compose_include_replacement_source_artifact_refs_replacement(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    include_dir = tmp_path / "includes"
    include_dir.mkdir()
    original = include_dir / "original.yaml"
    replacement = include_dir / "replacement.yaml"

    original.write_text("kind: original\n", encoding="utf-8")
    replacement.write_text("kind: replacement\n", encoding="utf-8")
    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  model:\n"
        "    _include_: ./includes/original.yaml\n",
        encoding="utf-8",
    )

    composed = compose_config(base, overrides=("pipeline.model._include_=./includes/replacement.yaml",))

    include_artifacts = [artifact for artifact in composed.source_artifacts if artifact.kind == "include"]
    assert len(include_artifacts) == 1
    assert include_artifacts[0].path == str(replacement.resolve())
    assert include_artifacts[0].path != str(original.resolve())

    source_artifact_references = cast(
        list[dict[str, Any]],
        cast(dict[str, Any], composed.manifest.to_dict()["metadata"])["source_artifact_references"],
    )
    serialized_references = json.dumps(source_artifact_references, sort_keys=True)
    assert str(replacement.resolve()) in serialized_references
    assert str(original.resolve()) not in serialized_references


def test_public_compose_brand_new_include_addition_creates_source_artifact_ref(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    components = tmp_path / "components"
    components.mkdir()
    dataset = components / "dataset.yaml"

    dataset.write_text("kind: tabular\nrows: 100\n", encoding="utf-8")
    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  existing: true\n",
        encoding="utf-8",
    )

    composed = compose_config(base, overrides=("+pipeline.dataset._include_=./components/dataset.yaml",))

    include_artifacts = [artifact for artifact in composed.source_artifacts if artifact.kind == "include"]
    assert len(include_artifacts) == 1
    assert include_artifacts[0].path == str(dataset.resolve())

    source_artifact_references = cast(
        list[dict[str, Any]],
        composed.manifest.metadata["source_artifact_references"],
    )
    assert any(
        reference["kind"] == "include" and reference["path"] == str(dataset.resolve())
        for reference in source_artifact_references
    )


def test_public_compose_redaction_preserves_resolver_expressions_in_artifacts(tmp_path: Path, monkeypatch) -> None:
    base = tmp_path / "base.yaml"
    base.write_text(
        "name: base\n"
        "paths:\n"
        "  root: ${oc.env:PHASE13_PROVENANCE_ROOT}\n"
        "pipeline:\n"
        "  data: ${paths.root}/value\n"
        "api_key: top-secret\n"
        "seed: 11\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("PHASE13_PROVENANCE_ROOT", "/tmp/phase13-root")
    composed = compose_config(base, overrides=("+pipeline.secret_token=sauce",))

    unresolved_pipeline = cast(dict[str, Any], composed.unresolved["pipeline"])
    redacted_pipeline = cast(dict[str, Any], composed.redacted["pipeline"])
    redacted_root = cast(dict[str, Any], composed.redacted)
    resolved_pipeline = cast(dict[str, Any], composed.resolved["pipeline"])

    assert unresolved_pipeline["data"] == "${paths.root}/value"
    assert redacted_pipeline["data"] == "${paths.root}/value"
    assert resolved_pipeline["data"] == "/tmp/phase13-root/value"
    assert redacted_root["api_key"] == REDACTION_MARKER
    assert redacted_pipeline["secret_token"] == REDACTION_MARKER

    security = cast(dict[str, Any], composed.provenance.metadata["security_facts"])
    artifact_safety = cast(dict[str, Any], security["artifact_safety"])
    assert artifact_safety["raw_source_bytes_included"] is False
    assert artifact_safety["resolved_runtime_values_included"] is False
    assert [record.label for record in composed.fingerprint_records] == [ARTIFACT_SAFE_FINGERPRINT_LABEL]
    assert composed.fingerprint_records[0].metadata["fingerprint_policy"] == ARTIFACT_SAFE_FINGERPRINT_POLICY
    assert composed.provenance.schema_version == 2
    assert composed.provenance.artifact_fingerprint == composed.fingerprint
    provenance_payload = composed.provenance.to_dict()
    assert provenance_payload["artifact_fingerprint"] == composed.fingerprint
    assert "resolved_fingerprint" not in provenance_payload
    provenance_fingerprint = cast(dict[str, Any], composed.provenance.metadata["fingerprint"])
    assert provenance_fingerprint["artifact_fingerprint"] == composed.fingerprint

    artifact_payload = {
        "manifest": composed.manifest.to_dict(),
        "source_artifacts": [record.to_dict() for record in composed.source_artifacts],
        "fingerprint_records": [record.to_dict() for record in composed.fingerprint_records],
        "provenance_metadata": composed.provenance.metadata,
        "redacted": composed.redacted,
    }
    serialized_artifacts = json.dumps(artifact_payload, sort_keys=True)
    assert "/tmp/phase13-root" not in serialized_artifacts
    assert "top-secret" not in serialized_artifacts
    assert "sauce" not in serialized_artifacts
    assert "resolved_fingerprint" not in serialized_artifacts


def test_public_compose_redacts_nested_secret_override_artifact_provenance(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text(
        "name: base\n"
        "pipeline: {}\n",
        encoding="utf-8",
    )

    composed = compose_config(
        base,
        overrides=('+pipeline.auth={"token":"nested-sauce","mode":"safe"}',),
    )

    provenance_payload = composed.provenance.to_dict()
    provenance_override = cast(list[dict[str, Any]], provenance_payload["overrides"])[0]
    assert provenance_override["raw"] == REDACTION_MARKER
    assert provenance_override["redacted"] is True
    assert provenance_override["value"] == {"token": REDACTION_MARKER, "mode": "safe"}

    ordinary_overrides = cast(list[dict[str, Any]], composed.provenance.metadata["ordinary_overrides"])
    assert ordinary_overrides[0]["raw"] == REDACTION_MARKER
    assert ordinary_overrides[0]["value"] == {"token": REDACTION_MARKER, "mode": "safe"}

    security = cast(dict[str, Any], composed.provenance.metadata["security_facts"])
    warnings = cast(list[dict[str, Any]], security["plaintext_secret_override_warnings"])
    assert warnings[0]["override_path"] == "pipeline.auth"
    assert warnings[0]["override_raw"] == REDACTION_MARKER

    artifact_payload = {
        "provenance": provenance_payload,
        "manifest": composed.manifest.to_dict(),
        "provenance_metadata": composed.provenance.metadata,
        "redacted": composed.redacted,
    }
    serialized_artifacts = json.dumps(artifact_payload, sort_keys=True)
    assert "nested-sauce" not in serialized_artifacts
    assert "safe" in serialized_artifacts


def test_public_compose_records_resolver_and_override_facts(tmp_path: Path, monkeypatch) -> None:
    base = tmp_path / "base.yaml"
    base.write_text(
        "name: base\n"
        "paths:\n"
        "  root: ${oc.env:PHASE13_PATH}\n"
        "pipeline:\n"
        "  value: ${paths.root}/value\n"
        "note: keep\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("PHASE13_PATH", "/tmp/phase13")
    composed = compose_config(base, overrides=("+pipeline.secret_token=keep-secret",))

    security = cast(dict[str, Any], composed.provenance.metadata["security_facts"])
    warnings = cast(list[dict[str, Any]], security["plaintext_secret_override_warnings"])
    assert warnings
    assert warnings[0]["warning_type"] == "plaintext_secret_override"
    assert warnings[0]["override_path"] == "pipeline.secret_token"
    assert warnings[0]["override_raw"] == REDACTION_MARKER

    resolver_records = cast(
        list[dict[str, Any]],
        composed.provenance.metadata["resolver_records"],
    )
    assert resolver_records
    assert resolver_records[0]["resolver"] == "oc.env"
    assert resolver_records[0]["config_path"] == "$.paths.root"
    assert resolver_records[0]["token"] == "${oc.env:PHASE13_PATH}"
    assert resolver_records[0]["expression"] == "oc.env:PHASE13_PATH"
    manifest_metadata = cast(dict[str, Any], composed.manifest.to_dict()["metadata"])
    assert manifest_metadata["resolver_records"] == resolver_records
    fingerprint_resolver_facts = cast(
        list[dict[str, Any]],
        composed.fingerprint_records[0].metadata["resolver_facts"],
    )
    assert fingerprint_resolver_facts[0]["config_path"] == "$.paths.root"

    metadata_records = cast(
        dict[str, Any],
        composed.provenance.metadata["source_fact_records"],
    )
    assert "sources" in metadata_records
    assert "include_sites" in metadata_records
    assert "include_recomposition_contexts" in metadata_records
    assert "local_customizations" in metadata_records

    ordinary_overrides = cast(list[dict[str, Any]], composed.provenance.metadata["ordinary_overrides"])
    assert ordinary_overrides[0]["raw"] == REDACTION_MARKER
    assert ordinary_overrides[0]["value"] == REDACTION_MARKER


def test_public_compose_builds_artifacts_before_runtime_interpolation_and_keeps_digests_env_free(
    tmp_path: Path,
    monkeypatch,
) -> None:
    base = tmp_path / "base.yaml"
    base.write_text(
        "name: base\n"
        "paths:\n"
        "  root: ${oc.env:PHASE4_RUNTIME_ROOT}\n"
        "pipeline:\n"
        "  value: ${paths.root}/value\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("PHASE4_RUNTIME_ROOT", "/runtime/one")
    first = inspect_config_composition(base)
    monkeypatch.setenv("PHASE4_RUNTIME_ROOT", "/runtime/two")
    second = inspect_config_composition(base)

    stage_names = [stage.name for stage in first.stages]
    assert stage_names.index("artifact_placeholders") < stage_names.index("runtime_interpolation")
    assert stage_names.index("provenance") < stage_names.index("runtime_interpolation")
    assert stage_names.index("fingerprint") < stage_names.index("runtime_interpolation")
    first_paths = cast(dict[str, Any], first.resolved["paths"])
    second_paths = cast(dict[str, Any], second.resolved["paths"])
    assert first_paths["root"] == "/runtime/one"
    assert second_paths["root"] == "/runtime/two"
    assert first.fingerprint == second.fingerprint
    assert first.provenance.artifact_fingerprint == second.provenance.artifact_fingerprint
    assert first.provenance.metadata["fingerprint"] == second.provenance.metadata["fingerprint"]
    assert first.manifest.to_dict() == second.manifest.to_dict()
    assert [record.to_dict() for record in first.fingerprint_records] == [
        record.to_dict() for record in second.fingerprint_records
    ]

    serialized = json.dumps(
        {
            "provenance": first.provenance.to_dict(),
            "manifest": first.manifest.to_dict(),
            "fingerprint_records": [record.to_dict() for record in first.fingerprint_records],
        },
        sort_keys=True,
    )
    assert "/runtime/one" not in serialized
    assert "/runtime/two" not in serialized


def test_public_compose_records_final_value_authorship_without_values(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    included = tmp_path / "included.yaml"
    included.write_text("from_include: included-value\n", encoding="utf-8")
    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  model:\n"
        "    _include_: ./included.yaml\n"
        "  token: base-secret\n",
        encoding="utf-8",
    )
    overlay.write_text("pipeline:\n  overlay_value: overlay-authored\n", encoding="utf-8")

    composed = compose_config(
        base,
        overlays=(overlay,),
        overrides=("pipeline.token=override-secret", "+pipeline.added=safe-value"),
    )

    source_facts = cast(dict[str, Any], composed.provenance.metadata["source_fact_records"])
    authorship = cast(list[dict[str, Any]], source_facts["final_value_authorship"])
    by_path = {record["config_path"]: record for record in authorship}

    assert by_path["$.pipeline.overlay_value"]["source_kind"] == "overlay"
    assert by_path["$.pipeline.model.from_include"]["source_kind"] == "include"
    assert by_path["$.pipeline.token"]["source_kind"] == "ordinary_override"
    assert by_path["$.pipeline.token"]["details"]["override_redacted"] is True
    assert by_path["$.pipeline.added"]["source_kind"] == "ordinary_override"

    serialized = json.dumps({"authorship": authorship}, sort_keys=True)
    assert "override-secret" not in serialized
    assert "base-secret" not in serialized
    assert "pipeline.token=override-secret" not in serialized
    assert "safe-value" not in serialized


def test_public_compose_records_recipe_source_artifacts_when_safe(tmp_path: Path) -> None:
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

    composed = compose_config(base, recipe_catalog=catalog)

    recipe_records = [artifact for artifact in composed.source_artifacts if artifact.kind == "recipe"]
    assert recipe_records
    recipe_record = recipe_records[0]
    assert recipe_record.path == "pipeline"
    manifest_recipes = cast(
        list[dict[str, Any]],
        composed.manifest.metadata["recipe_manifest"],
    )
    assert len(manifest_recipes) == 1
    assert manifest_recipes[0]["expanded_hash"] == recipe_record.content_digest
    assert manifest_recipes[0]["name"] == "arg"
    assert cast(list[dict[str, Any]], composed.manifest.metadata["source_artifact_references"])[-1] == {
        "kind": "recipe",
        "order": recipe_record.order,
        "path": recipe_record.path,
        "content_digest": recipe_record.content_digest,
        "size_bytes": recipe_record.size_bytes,
    }


def test_public_compose_inspection_and_payload_artifacts_stay_in_sync(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  value: 1\n",
        encoding="utf-8",
    )

    inspection = inspect_config_composition(base)
    composed = inspection.to_composed_config()
    assert composed.source_artifacts == inspection.source_artifacts
    assert composed.fingerprint_records == inspection.fingerprint_records
    assert composed.manifest.source_artifacts == inspection.manifest.source_artifacts
    assert composed.provenance.metadata == inspection.provenance.metadata
