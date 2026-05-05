"""Config instantiate import-boundary tests."""

from __future__ import annotations

import subprocess
import sys
from textwrap import dedent

import pytest


pytestmark = pytest.mark.package


def test_import_config_instantiate_does_not_import_composition_or_runtime_layers() -> None:
    script = dedent(
        """
        import sys

        from loom.config.instantiate import instantiate

        if not callable(instantiate):
            raise SystemExit("loom.config.instantiate.instantiate is not callable")

        for forbidden in (
            "yaml",
            "omegaconf",
            "pydantic",
            "loom.pipeline",
            "loom.pipeline.execution",
            "loom.pipeline.stores",
            "loom.execution",
            "loom.stores",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.config.instantiate")
        print("ok")
        """
    )

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
