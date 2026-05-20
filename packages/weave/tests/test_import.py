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
