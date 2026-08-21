"""Import-boundary coverage for the explicit NVIDIA GPU adapter."""

from __future__ import annotations

import subprocess
import sys


def test_generic_and_explicit_gpu_imports_never_probe_nvidia_hardware() -> None:
    script = """
import subprocess

calls = []
def forbidden(*args, **kwargs):
    calls.append((args, kwargs))
    raise AssertionError("import attempted command execution")

subprocess.run = forbidden
import loom
import loom.queue
import loom.queue.gpu
import loom.queue.gpu.nvidia
from loom.queue.gpu.nvidia import NvidiaSmiGpuInventoryProvider

NvidiaSmiGpuInventoryProvider()
assert calls == []
"""

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
