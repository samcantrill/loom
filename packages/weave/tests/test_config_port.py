"""Package-local tests for the ported config implementation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from weave import (
    RecipeCatalog,
    check_config_targets,
    compose_config,
    inspect_config_composition,
    instantiate,
)
from weave.errors import ConfigErrorContext, ConfigIncludeResolutionError
from weave.fingerprints import ARTIFACT_SAFE_FINGERPRINT_LABEL
from weave.recipes.load import RecipePluginRecord, load_recipe_entry_points


pytestmark = pytest.mark.package

REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_PROJECT_ROOT = REPO_ROOT / "tests/fixtures/config/golden_project"
GOLDEN_PATH = REPO_ROOT / "tests/golden/config/extraction-v23"
PROJECT_PLACEHOLDER = "<golden_project>"


def test_public_api_composes_without_importing_loom() -> None:
    script = f"""
import pathlib
import sys

sys.path.insert(0, {str((REPO_ROOT / "packages/weave/src").resolve())!r})
from weave import RecipeCatalog, compose_config

project = pathlib.Path({str(GOLDEN_PROJECT_ROOT.resolve())!r})
catalog = RecipeCatalog()

def annotate(*, value: str, tag: str):
    return {{"annotation": f"{{tag}}:{{value}}", "value": value}}

catalog.register("annotate", annotate)
composed = compose_config(project / "base.yaml", recipe_catalog=catalog)
assert composed.resolved["pipeline"]["recipe_node"]["value"] == "base"

for forbidden in [name for name in sys.modules if name == "loom" or name.startswith("loom.")]:
    raise SystemExit(f"weave imported Loom module {{forbidden}}")
print("ok")
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_weave_golden_artifacts_match_phase_1_baseline() -> None:
    expected_files = {
        path.name: cast(Any, json.loads(path.read_text(encoding="utf-8")))
        for path in GOLDEN_PATH.glob("*.json")
    }
    for name, actual in _build_weave_artifacts().items():
        assert name in expected_files, f"Missing golden file {name}"
        assert _normalize_fixture_paths(actual, root=GOLDEN_PROJECT_ROOT) == _normalize_fixture_paths(
            expected_files[name],
            root=GOLDEN_PROJECT_ROOT,
        ), f"Mismatch for {name}"


def test_recipe_entry_point_loader_is_weave_owned() -> None:
    catalog = RecipeCatalog()
    record = RecipePluginRecord(
        group="loom.recipes",
        name="annotate",
        value=f"{__name__}:entry_point_recipe",
        package="demo",
        package_version="1",
    )

    result = load_recipe_entry_points(records=(record,), catalog=catalog, strict=True)

    assert result.ok
    assert catalog.get("annotate")(value="x", tag="t") == {"annotation": "t:x", "value": "x"}


def test_instantiate_and_target_checks_use_weave_errors() -> None:
    value = {
        "item": {
            "_target_": "builtins:dict",
            "value": 1,
        }
    }

    result = instantiate(value)
    checks = check_config_targets(value)

    assert result == {"item": {"value": 1}}
    assert checks.target_count == 1
    assert checks.checked_paths == ("$.item",)


def entry_point_recipe(*, value: str, tag: str) -> dict[str, Any]:
    return {"annotation": f"{tag}:{value}", "value": value}


def _build_weave_artifacts() -> dict[str, Any]:
    base = GOLDEN_PROJECT_ROOT / "base.yaml"
    overlay = GOLDEN_PROJECT_ROOT / "overlay.yaml"
    broken = GOLDEN_PROJECT_ROOT / "broken.yaml"
    catalog = RecipeCatalog()

    def annotate(*, value: str, tag: str) -> dict[str, Any]:
        return {"annotation": f"{tag}:{value}", "value": value}

    annotate.__module__ = "test_config_extraction_golden_artifacts_contract"
    annotate.__qualname__ = "_build_expected_artifacts.<locals>.annotate"
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
        compose_config(broken)
    except ConfigIncludeResolutionError as exc:
        structured_error = cast(dict[str, Any], exc.to_dict())
        error_context = cast(dict[str, object], structured_error["context"])
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
