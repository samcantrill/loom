"""Package-level import-boundary tests."""

from __future__ import annotations

import subprocess
import sys
from textwrap import dedent

import pytest


pytestmark = pytest.mark.package


def test_import_does_not_import_deferred_modules() -> None:
    script = dedent(
        """
        import sys

        import loom

        for forbidden in ("loom.config", "loom.pipeline", "loom.cli"):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported eagerly")
        print("ok")
        """
    )

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_serialization_does_not_import_io() -> None:
    script = dedent(
        """
        import sys

        import loom.serialization

        if "loom.io" in sys.modules:
            raise SystemExit("loom.io imported through serialization")
        print("ok")
        """
    )

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_io_does_not_import_config_or_pipeline() -> None:
    script = dedent(
        """
        import sys

        import loom.io

        for forbidden in ("loom.config", "loom.pipeline", "loom.cli"):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.io")
        print("ok")
        """
    )

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
