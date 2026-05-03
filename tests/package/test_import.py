from importlib.resources import files

import pytest

import loom

pytestmark = pytest.mark.package


def test_package_imports() -> None:
    assert loom.__version__


def test_package_declares_public_exports() -> None:
    assert loom.__all__ == ["__version__"]


def test_package_includes_typing_marker() -> None:
    assert files("loom").joinpath("py.typed").is_file()
