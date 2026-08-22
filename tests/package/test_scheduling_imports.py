"""The scheduling public boundary stays dependency-light in a fresh process."""

from __future__ import annotations

import subprocess
import sys


def test_scheduling_import_does_not_load_pipeline() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import loom.scheduling; assert not any(name == 'loom.pipeline' or name.startswith('loom.pipeline.') for name in sys.modules)",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
