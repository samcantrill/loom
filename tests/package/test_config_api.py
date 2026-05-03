"""Package-level tests for config API behavior."""

from __future__ import annotations

import inspect
import subprocess
import sys
from textwrap import dedent

import pytest

from loom.config import ComposedConfig


pytestmark = pytest.mark.package


def test_config_exports_and_signature() -> None:
    from loom.config import ConfigError, compose_config, instantiate, register_recipe

    assert ConfigError
    assert ComposedConfig
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


def test_import_config_module_only() -> None:
    script = dedent(
        """
        import loom.config

        assert hasattr(loom.config, 'ComposedConfig')
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
