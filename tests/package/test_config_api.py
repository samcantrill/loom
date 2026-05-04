"""Package-level tests for config API behavior."""

from __future__ import annotations

import importlib
import inspect
import subprocess
import sys
from textwrap import dedent

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

from loom.config import ComposedConfig


pytestmark = [pytest.mark.package, pytest.mark.optional_dependency]


def test_config_exports_and_signature() -> None:
    from loom.config import ConfigError, Recipe, RecipeCatalog, compose_config, instantiate, register_recipe

    assert ConfigError
    assert ComposedConfig
    assert Recipe
    assert RecipeCatalog
    assert compose_config
    assert instantiate
    assert register_recipe

    signature = inspect.signature(compose_config)
    params = list(signature.parameters.values())
    assert len(params) == 4
    assert params[0].name == "config_path"
    assert params[1].name == "overlays"
    assert params[2].name == "overrides"
    assert params[3].name == "recipe_catalog"
    assert params[1].default == ()
    assert params[2].default == ()
    assert params[3].default is None

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


def test_config_instantiate_callable_survives_submodule_import_order() -> None:
    import loom.config

    package_instantiate = loom.config.instantiate
    assert package_instantiate.__module__ == "loom.config.api"

    instantiate_submodule = importlib.import_module("loom.config.instantiate")
    assert inspect.ismodule(instantiate_submodule)
    assert callable(instantiate_submodule.instantiate)
    assert callable(instantiate_submodule.import_target)
    assert loom.config.instantiate is package_instantiate

    importlib.reload(instantiate_submodule)
    assert loom.config.instantiate is package_instantiate
    assert loom.config.instantiate({"value": ("a", "b")}) == {"value": ["a", "b"]}


def test_import_config_module_only() -> None:
    script = dedent(
        """
        import loom.config

        assert hasattr(loom.config, 'ComposedConfig')
        assert hasattr(loom.config, 'Recipe')
        assert hasattr(loom.config, 'RecipeCatalog')
        assert hasattr(loom.config, 'compose_config')
        assert hasattr(loom.config, 'instantiate')
        assert hasattr(loom.config, 'register_recipe')
        assert hasattr(loom.config, 'ConfigError')
        print('ok')
        """
    )

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
