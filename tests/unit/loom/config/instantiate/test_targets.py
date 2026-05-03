"""Unit tests for target import helpers."""

import pytest

from loom.config.errors import TargetImportError
from loom.config.instantiate import import_target


def test_import_target_dotted_path() -> None:
    target = import_target("tests.support.config_samples.concat")
    assert target("a", "b") == "ab"


def test_import_target_colon_path() -> None:
    target = import_target("tests.support.config_samples:concat")
    assert target("a", "b") == "ab"


def test_import_target_rejects_invalid_forms() -> None:
    with pytest.raises(TargetImportError):
        import_target("not-a-module")
    with pytest.raises(TargetImportError):
        import_target("")
    with pytest.raises(TargetImportError):
        import_target("tests.support.config_samples:missing")
    with pytest.raises(TargetImportError):
        import_target("tests.support.config_samples:bad.object")
