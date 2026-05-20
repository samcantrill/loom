"""Contract tests for phase-1 golden config extraction artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

from loom.config import RecipeCatalog, inspect_config_composition
from loom.config.errors import ConfigErrorContext, ConfigIncludeResolutionError
from loom.config.fingerprints import ARTIFACT_SAFE_FINGERPRINT_LABEL

pytestmark = [pytest.mark.contract, pytest.mark.optional_dependency]

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_PROJECT_ROOT = REPO_ROOT / "tests/fixtures/config/golden_project"
GOLDEN_PATH = REPO_ROOT / "tests/golden/config/extraction-v23"
PROJECT_PLACEHOLDER = "<golden_project>"


def _normalize_path(value: str, *, root: Path) -> str:
    root_path = str(root.resolve())
    if value == root_path:
        return PROJECT_PLACEHOLDER
    if value.startswith(root_path + "/") or value.startswith(root_path + "\\"):
        return PROJECT_PLACEHOLDER + value[len(root_path) :]
    if root_path in value:
        return value.replace(root_path, PROJECT_PLACEHOLDER)
    return value


def _normalize_fixture_paths(value: Any, *, root: Path) -> Any:
    if isinstance(value, dict):
        return {key: _normalize_fixture_paths(item, root=root) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_fixture_paths(item, root=root) for item in value]
    if isinstance(value, tuple):
        return [_normalize_fixture_paths(item, root=root) for item in value]
    if isinstance(value, str):
        return _normalize_path(value, root=root)
    return value


def _build_expected_artifacts() -> dict[str, Any]:
    base = GOLDEN_PROJECT_ROOT / "base.yaml"
    overlay = GOLDEN_PROJECT_ROOT / "overlay.yaml"
    broken = GOLDEN_PROJECT_ROOT / "broken.yaml"
    catalog = RecipeCatalog()

    def annotate(*, value: str, tag: str) -> dict[str, Any]:
        return {"annotation": f"{tag}:{value}", "value": value}

    annotate.__module__ = "test_config_extraction_golden_artifacts_contract"
    catalog.register("annotate", annotate)

    inspection = inspect_config_composition(
        base,
        overlays=(overlay,),
        overrides=("pipeline.settings.mode=override", "+pipeline.extra=from-overrides"),
        recipe_catalog=catalog,
        include_raw_source_snapshots=True,
    )

    artifact_records = {
        record.label: record.to_dict() for record in inspection.fingerprint_records
    }
    if ARTIFACT_SAFE_FINGERPRINT_LABEL not in artifact_records:
        raise AssertionError("artifact-safe config fingerprint record is missing")

    try:
        inspect_config_composition(broken)
    except ConfigIncludeResolutionError as exc:
        structured_error = cast(dict[str, Any], exc.to_dict())
        error_context = cast(dict[str, object], structured_error["context"])
        # Ensure the public error payload round-trips through public context parsing.
        assert ConfigErrorContext.from_dict(error_context) == exc.context
    else:
        raise AssertionError("Broken config fixture unexpectedly composed successfully")

    return {
        "resolved-config.json": inspection.resolved,
        "redacted-config.json": inspection.redacted,
        "composition-manifest.json": inspection.manifest.to_dict(),
        "recipe-manifest.json": list(inspection.recipe_manifest),
        "source-artifact-records.json": [
            record.to_dict() for record in inspection.source_artifacts
        ],
        "raw-source-snapshots.json": inspection.raw_source_snapshots.to_dict(),
        "config-fingerprint-record.json": artifact_records[ARTIFACT_SAFE_FINGERPRINT_LABEL],
        "structured-config-errors.json": structured_error,
    }


def _assert_golden_payload(name: str, expected: Any, actual: Any) -> None:
    assert _normalize_fixture_paths(actual, root=GOLDEN_PROJECT_ROOT) == _normalize_fixture_paths(
        expected, root=GOLDEN_PROJECT_ROOT
    ), f"Mismatch for {name}"


def test_config_extraction_golden_artifacts_match_expected() -> None:
    expected_files = {
        path.name: cast(Any, json.loads(path.read_text(encoding="utf-8")))
        for path in GOLDEN_PATH.glob("*.json")
    }
    for name, actual in _build_expected_artifacts().items():
        assert name in expected_files, f"Missing golden file {name}"
        _assert_golden_payload(name, expected_files[name], actual)
