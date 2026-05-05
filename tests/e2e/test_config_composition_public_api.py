"""End-to-end config composition through public Python APIs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest


pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

from loom.config import (
    RecipeCatalog,
    compare_config_artifact_fingerprints,
    compose_config,
    inspect_config_composition,
)
from loom.config.redaction import REDACTION_MARKER
from loom.serialization import PlainData

pytestmark = pytest.mark.e2e


def _step_recipe(*, name: str, input: str) -> dict[str, PlainData]:
    return {"name": name, "input": input, "enabled": True, "output": f"{name}:{input}"}


def _write_config_tree(root: Path) -> Path:
    config_root = root / "configs"
    (config_root / "workflow" / "dataset" / "reader").mkdir(parents=True)
    (config_root / "swaps" / "reader").mkdir(parents=True)

    base = config_root / "experiment.yaml"
    overlay = config_root / "overlay.yaml"
    baseline = config_root / "workflow" / "dataset" / "baseline.yaml"
    standard_reader = config_root / "workflow" / "dataset" / "reader" / "standard.yaml"
    replacement = config_root / "swaps" / "dataset.yaml"
    fast_reader = config_root / "swaps" / "reader" / "fast.yaml"

    base.write_text(
        "name: composition-e2e\n"
        "paths:\n"
        "  runtime_root: ${oc.env:LOOM_E2E_RUNTIME_ROOT}\n"
        "workflow:\n"
        "  dataset:\n"
        "    _include_: baseline\n"
        "    split: train\n"
        "  processor:\n"
        "    _recipe_: step\n"
        "    name: normalize\n"
        "    input: ${workflow.dataset.reader.kind}\n"
        "  auth:\n"
        "    api_key: ${oc.env:LOOM_E2E_API_KEY}\n"
        "  parameters:\n"
        "    seed: 7\n",
        encoding="utf-8",
    )
    overlay.write_text(
        "workflow:\n"
        "  dataset:\n"
        "    split: validation\n"
        "  parameters:\n"
        "    seed: 13\n",
        encoding="utf-8",
    )
    baseline.write_text(
        "kind: baseline\n"
        "reader:\n"
        "  _include_: standard\n"
        "  delimiter: ','\n",
        encoding="utf-8",
    )
    standard_reader.write_text("kind: csv\nbatch_size: 64\n", encoding="utf-8")
    replacement.write_text(
        "kind: replacement\n"
        "reader:\n"
        "  _include_: fast\n"
        "  delimiter: '\\t'\n"
        "feature_count: 12\n",
        encoding="utf-8",
    )
    fast_reader.write_text("kind: parquet\nbatch_size: 32\n", encoding="utf-8")
    return base


def _assert_no_composition_markers(value: PlainData) -> None:
    if isinstance(value, dict):
        for marker in ("_include_", "_replace_", "_copy_"):
            assert marker not in value
        for child in value.values():
            _assert_no_composition_markers(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_composition_markers(child)


def test_public_python_config_composition_e2e(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _write_config_tree(tmp_path)
    overlay = base.parent / "overlay.yaml"
    catalog = RecipeCatalog()
    catalog.register("step", _step_recipe)
    overrides = (
        "workflow.dataset._include_=./swaps/dataset.yaml",
        "workflow.parameters.seed=21",
        "+workflow.parameters.run_label=e2e",
        "+workflow.auth.token=inline-secret",
    )

    monkeypatch.setenv("LOOM_E2E_RUNTIME_ROOT", "/runtime/one")
    monkeypatch.setenv("LOOM_E2E_API_KEY", "api-key-one")
    inspection = inspect_config_composition(
        base,
        overlays=(overlay,),
        overrides=overrides,
        recipe_catalog=catalog,
    )
    composed = inspection.to_composed_config()

    workflow = cast(dict[str, Any], composed.resolved["workflow"])
    dataset = cast(dict[str, Any], workflow["dataset"])
    reader = cast(dict[str, Any], dataset["reader"])
    processor = cast(dict[str, Any], workflow["processor"])
    auth = cast(dict[str, Any], workflow["auth"])
    parameters = cast(dict[str, Any], workflow["parameters"])

    assert dataset == {
        "kind": "replacement",
        "reader": {"kind": "parquet", "batch_size": 32, "delimiter": "\\t"},
        "feature_count": 12,
        "split": "validation",
    }
    assert reader["kind"] == "parquet"
    assert processor == {
        "name": "normalize",
        "input": "parquet",
        "enabled": True,
        "output": "normalize:parquet",
    }
    assert auth["api_key"] == "api-key-one"
    assert auth["token"] == "inline-secret"
    assert parameters == {"seed": 21, "run_label": "e2e"}
    _assert_no_composition_markers(composed.unresolved)
    _assert_no_composition_markers(composed.resolved)

    redacted_auth = cast(dict[str, Any], cast(dict[str, Any], composed.redacted["workflow"])["auth"])
    assert redacted_auth == {"api_key": REDACTION_MARKER, "token": REDACTION_MARKER}

    assert inspection.stage("file_include_expansion") is not None
    assert inspection.stage("recipe_expansion") is not None
    assert inspection.stage("provenance") is not None
    assert composed.manifest.schema_version == 1
    assert composed.provenance.schema_version == 1
    assert [record.kind for record in composed.source_artifacts] == [
        "base",
        "overlay",
        "include",
        "include",
        "recipe",
    ]
    source_paths = {record.path for record in composed.source_artifacts}
    assert str((base.parent / "swaps" / "dataset.yaml").resolve()) in source_paths
    assert str((base.parent / "swaps" / "reader" / "fast.yaml").resolve()) in source_paths
    assert str((base.parent / "workflow" / "dataset" / "baseline.yaml").resolve()) not in source_paths

    artifact_payload = {
        "manifest": composed.manifest.to_dict(),
        "source_artifacts": [record.to_dict() for record in composed.source_artifacts],
        "fingerprint_records": [record.to_dict() for record in composed.fingerprint_records],
        "provenance": composed.provenance.to_dict(),
        "redacted": composed.redacted,
    }
    serialized_artifacts = json.dumps(artifact_payload, sort_keys=True)
    assert "/runtime/one" not in serialized_artifacts
    assert "api-key-one" not in serialized_artifacts
    assert "inline-secret" not in serialized_artifacts
    assert "oc.env:LOOM_E2E_RUNTIME_ROOT" in serialized_artifacts
    assert "oc.env:LOOM_E2E_API_KEY" in serialized_artifacts

    assert composed.raw_source_snapshots.enabled is False
    assert composed.raw_source_snapshots.payloads == ()
    assert all(reference.payload_id is None for reference in composed.raw_source_snapshots.references)
    assert all(
        reference.availability == "disabled" and reference.reason == "not_requested"
        for reference in composed.raw_source_snapshots.references
        if reference.kind != "recipe"
    )
    assert all(
        reference.availability == "unavailable"
        and reference.reason == "unsupported_source_kind"
        for reference in composed.raw_source_snapshots.references
        if reference.kind == "recipe"
    )

    monkeypatch.setenv("LOOM_E2E_RUNTIME_ROOT", "/runtime/two")
    monkeypatch.setenv("LOOM_E2E_API_KEY", "api-key-two")
    recomposed = compose_config(
        base,
        overlays=(overlay,),
        overrides=overrides,
        recipe_catalog=catalog,
    )
    assert recomposed.resolved["paths"] == {"runtime_root": "/runtime/two"}
    assert recomposed.fingerprint == composed.fingerprint
    assert (
        compare_config_artifact_fingerprints(
            left=composed.fingerprint_records[0],
            right=recomposed.fingerprint_records[0],
        ).status
        == "match"
    )

    with_snapshots = compose_config(
        base,
        overlays=(overlay,),
        overrides=overrides,
        recipe_catalog=catalog,
        include_raw_source_snapshots=True,
    )
    assert with_snapshots.fingerprint == composed.fingerprint
    assert with_snapshots.raw_source_snapshots.enabled is True
    assert with_snapshots.raw_source_snapshots.payloads
    assert all(
        "content" not in reference.to_dict()
        for reference in with_snapshots.raw_source_snapshots.references
    )
    assert any(
        payload.content.startswith("name: composition-e2e\n")
        for payload in with_snapshots.raw_source_snapshots.payloads
    )
