"""Import-boundary tests for opt-in contract support."""

import subprocess
import sys
from textwrap import dedent

import pytest


pytestmark = pytest.mark.package


def test_testing_is_opt_in_and_import_light() -> None:
    script = dedent(
        """
        import sys

        import loom

        if "loom.testing" in sys.modules or "testing" in loom.__all__:
            raise SystemExit("loom.testing entered the root package")

        import loom.testing

        for forbidden in ("pytest", "loom.plugins", "loom.cli", "weave"):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.testing")
        print("ok")
        """
    )

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
