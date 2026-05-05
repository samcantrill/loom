"""Unit tests for target import helpers."""

from collections.abc import Callable
from typing import cast

import pytest

from loom.config.errors import TargetImportError
from loom.config.instantiate import import_target


def test_import_target_dotted_path() -> None:
    target = cast(Callable[[str, str], str], import_target("tests.support.config_samples.concat"))
    assert target("a", "b") == "ab"


def test_import_target_colon_path() -> None:
    target = cast(Callable[[str, str], str], import_target("tests.support.config_samples:concat"))
    assert target("a", "b") == "ab"


def test_import_target_rejects_invalid_forms() -> None:
    with pytest.raises(TargetImportError):
        import_target("not-a-module")
    with pytest.raises(TargetImportError):
        import_target("")
    with pytest.raises(TargetImportError):
        import_target("tests.support.config_samples:tests.support.config_samples.Parent.Inner")
    with pytest.raises(TargetImportError):
        import_target("tests.support.config_samples:missing")
    with pytest.raises(TargetImportError):
        import_target("tests.support.config_samples:bad.object")


def test_import_target_rejects_invalid_target_syntax() -> None:
    invalid_targets = [
        "not-a-module",  # missing dotted object segment
        "tests.support.config_samples:",
        "tests.support.config_samples:   ",
        "tests.support.config_samples:concat:",
        "tests.support.config_samples:concat::name",
        ":tests.support.config_samples:concat",
    ]
    for target in invalid_targets:
        with pytest.raises(TargetImportError):
            import_target(target)


def test_import_target_rejects_fallback_and_nested_lookup_for_dotted_path() -> None:
    # If fallback import splitting were implemented, this would resolve
    # Parent.Inner via `tests.support.config_samples` attribute lookups.
    with pytest.raises(TargetImportError):
        import_target("tests.support.config_samples.Parent.Inner")


def test_import_target_rejects_nested_lookup_for_colon_path() -> None:
    with pytest.raises(TargetImportError):
        import_target("tests.support.config_samples:Parent.Inner")
