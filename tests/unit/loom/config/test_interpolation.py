"""Unit tests for interpolation wrapping."""

import pytest

from loom.config.errors import ConfigInterpolationError
from loom.config.interpolation import resolve_interpolation


def test_resolve_simple_config_node_interpolation() -> None:
    resolved = resolve_interpolation({"paths": {"root": "root", "child": "${paths.root}/child"}})
    paths = resolved["paths"]
    assert isinstance(paths, dict)
    assert paths["child"] == "root/child"


def test_reject_resolver_style_interpolation() -> None:
    with pytest.raises(ConfigInterpolationError):
        resolve_interpolation({"value": "${env:HOME}"})


def test_reject_unresolved_interpolation() -> None:
    with pytest.raises(ConfigInterpolationError):
        resolve_interpolation({"value": "${missing.path}"})
