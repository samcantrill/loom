"""Package-level import smoke tests."""

import tomllib
from importlib.resources import files
from pathlib import Path

import pytest

import loom

pytestmark = pytest.mark.package


def test_package_imports() -> None:
    assert loom.__version__


def test_package_declares_public_exports() -> None:
    assert loom.__all__ == [
        "__version__",
        "ResourceRef",
        "InMemoryManifest",
        "ManifestView",
        "Record",
        "ArtifactAddress",
        "ArtifactRef",
        "Fingerprint",
        "hash_mapping",
    ]


def test_import_lom_io_package() -> None:
    import loom.io

    assert loom.io.__all__


def test_import_loom_diagnostics_public_api() -> None:
    import loom.diagnostics

    assert loom.diagnostics.__all__ == [
        "PreflightStatus",
        "PreflightCheckStatus",
        "PreflightSeverity",
        "PreflightGroup",
        "PreflightCheckResult",
        "PreflightResult",
        "PreflightRequest",
        "PreflightError",
        "run_preflight",
    ]


def test_package_includes_typing_marker() -> None:
    assert files("loom").joinpath("py.typed").is_file()


def test_project_metadata_exposes_loom_console_script_entry_point() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]

    assert project["scripts"] == {"loom": "loom.cli.main:main"}
    assert "gui-scripts" not in project
