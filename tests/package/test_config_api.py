"""Package-level tests for config API behavior."""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path
import subprocess
import sys
from textwrap import dedent
from typing import Any, cast

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

from weave import ComposedConfig
from weave.errors import ConfigValidationError


pytestmark = [pytest.mark.package, pytest.mark.optional_dependency]


def test_config_exports_and_signature() -> None:
    from weave import (
        ConfigError,
        ConfigCompositionInspection,
        ConfigCompositionStageRecord,
        ARTIFACT_SAFE_FINGERPRINT_LABEL,
        ARTIFACT_SAFE_FINGERPRINT_POLICY,
        ARTIFACT_SAFE_RUNTIME_REPLAY,
        ConfigFingerprintComparison,
        RawSourceSnapshotBundle,
        RawSourceSnapshotPayload,
        RawSourceSnapshotReference,
        compare_config_artifact_fingerprints,
        Recipe,
        RecipeCatalog,
        inspect_config_composition,
        compose_config,
        compose_config_with_catalog,
        check_config_targets,
        instantiate,
        TargetCheckResult,
        register_recipe,
    )

    assert ConfigError
    assert ComposedConfig
    assert Recipe
    assert RecipeCatalog
    assert compose_config
    assert compose_config_with_catalog
    assert check_config_targets
    assert TargetCheckResult
    assert inspect_config_composition
    assert ConfigCompositionInspection
    assert ConfigCompositionStageRecord
    assert compare_config_artifact_fingerprints
    assert ConfigFingerprintComparison
    assert RawSourceSnapshotBundle
    assert RawSourceSnapshotPayload
    assert RawSourceSnapshotReference
    assert ARTIFACT_SAFE_FINGERPRINT_LABEL == "artifact_safe_config"
    assert ARTIFACT_SAFE_FINGERPRINT_POLICY == "artifact_safe_authored_composition_v1"
    assert ARTIFACT_SAFE_RUNTIME_REPLAY == "unavailable"
    assert instantiate
    assert register_recipe

    signature = inspect.signature(compose_config)
    params = list(signature.parameters.values())
    assert len(params) == 5
    assert params[0].name == "config_path"
    assert params[1].name == "overlays"
    assert params[2].name == "overrides"
    assert params[3].name == "recipe_catalog"
    assert params[4].name == "include_raw_source_snapshots"
    assert params[1].default == ()
    assert params[2].default == ()
    assert params[3].default is None
    assert params[4].default is False
    assert params[4].kind is inspect.Parameter.KEYWORD_ONLY

    catalog_signature = inspect.signature(compose_config_with_catalog)
    catalog_params = list(catalog_signature.parameters.values())
    assert len(catalog_params) == 5
    assert catalog_params[0].name == "config_path"
    assert catalog_params[1].name == "recipe_catalog"
    assert catalog_params[1].default is inspect.Signature.empty
    assert catalog_params[2].name == "overlays"
    assert catalog_params[3].name == "overrides"
    assert catalog_params[4].name == "include_raw_source_snapshots"
    assert catalog_params[1].kind is inspect.Parameter.KEYWORD_ONLY
    assert catalog_params[2].default == ()
    assert catalog_params[3].default == ()
    assert catalog_params[4].default is False
    assert catalog_params[4].kind is inspect.Parameter.KEYWORD_ONLY

    inspect_signature = inspect.signature(inspect_config_composition)
    inspect_params = list(inspect_signature.parameters.values())
    assert len(inspect_params) == 5
    assert inspect_params[0].name == "config_path"
    assert inspect_params[1].name == "overlays"
    assert inspect_params[2].name == "overrides"
    assert inspect_params[3].name == "recipe_catalog"
    assert inspect_params[4].name == "include_raw_source_snapshots"
    assert inspect_params[1].default == ()
    assert inspect_params[2].default == ()
    assert inspect_params[3].default is None
    assert inspect_params[4].default is False
    assert inspect_params[4].kind is inspect.Parameter.KEYWORD_ONLY

    register_signature = inspect.signature(register_recipe)
    register_params = list(register_signature.parameters.values())
    assert len(register_params) == 3
    assert register_params[0].name == "name"
    assert register_params[1].name == "recipe"
    assert register_params[2].name == "replace"

    instantiate_signature = inspect.signature(instantiate)
    instantiate_params = list(instantiate_signature.parameters.values())
    assert len(instantiate_params) == 2
    assert instantiate_params[0].name == "value"
    assert instantiate_params[1].name == "runtime"
    assert instantiate_params[1].default is None

    target_check_signature = inspect.signature(check_config_targets)
    target_check_params = list(target_check_signature.parameters.values())
    assert len(target_check_params) == 2
    assert target_check_params[0].name == "value"
    assert target_check_params[1].name == "skip_paths"
    assert target_check_params[1].default == ()


def test_config_instantiate_callable_survives_submodule_import_order() -> None:
    import weave

    package_instantiate = weave.instantiate
    assert package_instantiate.__module__ == "weave.instantiate.recursive"

    instantiate_submodule = importlib.import_module("weave.instantiate")
    assert inspect.ismodule(instantiate_submodule)
    assert callable(instantiate_submodule.instantiate)
    assert callable(instantiate_submodule.import_target)
    assert weave.instantiate is package_instantiate

    importlib.reload(instantiate_submodule)
    assert weave.instantiate is package_instantiate
    assert weave.instantiate({"value": ("a", "b")}) == {"value": ["a", "b"]}


def test_import_config_module_only() -> None:
    script = dedent(
        """
        import weave

        assert hasattr(weave, 'ComposedConfig')
        assert hasattr(weave, 'Recipe')
        assert hasattr(weave, 'RecipeCatalog')
        assert hasattr(weave, 'compose_config')
        assert hasattr(weave, 'compose_config_with_catalog')
        assert hasattr(weave, 'check_config_targets')
        assert hasattr(weave, 'inspect_config_composition')
        assert hasattr(weave, 'ConfigCompositionInspection')
        assert hasattr(weave, 'ConfigCompositionStageRecord')
        assert hasattr(weave, 'compare_config_artifact_fingerprints')
        assert hasattr(weave, 'ConfigFingerprintComparison')
        assert hasattr(weave, 'ARTIFACT_SAFE_FINGERPRINT_LABEL')
        assert hasattr(weave, 'ARTIFACT_SAFE_FINGERPRINT_POLICY')
        assert hasattr(weave, 'ARTIFACT_SAFE_RUNTIME_REPLAY')
        assert hasattr(weave, 'instantiate')
        assert hasattr(weave, 'TargetCheckResult')
        assert hasattr(weave, 'register_recipe')
        assert hasattr(weave, 'ConfigError')
        print('ok')
        """
    )

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_compose_signatures_reject_non_bool_raw_snapshot_flags(tmp_path: Path) -> None:
    from weave import RecipeCatalog, compose_config, compose_config_with_catalog, inspect_config_composition

    base = tmp_path / "base.yaml"
    base.write_text("name: base\npipeline: {}\n", encoding="utf-8")

    with pytest.raises(ConfigValidationError):
        compose_config(base, include_raw_source_snapshots=cast(Any, "true"))

    with pytest.raises(ConfigValidationError):
        compose_config_with_catalog(
            base,
            recipe_catalog=RecipeCatalog(),
            include_raw_source_snapshots=cast(Any, 1),
        )

    with pytest.raises(ConfigValidationError):
        inspect_config_composition(base, include_raw_source_snapshots=cast(Any, None))
