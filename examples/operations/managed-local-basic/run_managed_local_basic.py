"""Execute the maintained managed-local lifecycle journey."""

from __future__ import annotations

import runpy
from pathlib import Path
import sys


_LEGACY_JOURNEY = Path(__file__).resolve().parents[1] / "managed-local-queue"
sys.path.insert(0, str(_LEGACY_JOURNEY))
runpy.run_path(
    str(_LEGACY_JOURNEY / "run_managed_local_queue.py"),
    run_name="__main__",
)
