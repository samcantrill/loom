"""Package import smoke tests."""

import sys
import tomllib
from pathlib import Path

import pytest


pytestmark = pytest.mark.package



def test_import_weave_package_smoke() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    import weave

    assert hasattr(weave, "__version__")
    assert weave.__version__ == "0.1.0"
    assert "loom" not in sys.modules


def test_package_metadata_declares_config_runtime_dependencies() -> None:
    root = Path(__file__).resolve().parents[1]
    metadata = tomllib.loads((root / "pyproject.toml").read_text())

    assert set(metadata["project"]["dependencies"]) == {
        "omegaconf>=2.3",
        "pydantic>=2",
        "pyyaml>=6",
    }



def test_public_argv_import_surface_is_narrow() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    import weave
    import weave.api as api

    assert weave.compose_config_from_argv is api.compose_config_from_argv
    assert "compose_config_from_argv" in dir(weave)

    detailed_names = {
        "inspect_config_from_argv",
        "ConfigArgvCompositionResult",
        "ConfigArgvInspectionResult",
        "ConfigArgvWarning",
        "ArgvScopedOverlay",
        "ArgvValueOverride",
        "ScopedOverlayCandidate",
        "ArgvUnparsedArg",
        "ParsedConfigArgv",
        "parse_config_argv",
    }
    for name in detailed_names:
        assert not hasattr(weave, name)

    for name in detailed_names - {"parse_config_argv"}:
        assert hasattr(api, name)
    assert not hasattr(api, "parse_config_argv")
    assert "loom" not in sys.modules
