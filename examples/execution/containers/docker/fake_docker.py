"""Pure command-availability fixture retained by selected-Docker preflight."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import sys


def activate_fake_docker(output_root: Path) -> Path:
    """Install a version-only command and prepend its directory to PATH."""
    bin_dir = output_root / "fake-docker-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    command = bin_dir / "docker"
    command.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    print('Docker version 27.0.0, build loom-preflight-fixture')\n"
        "else:\n"
        "    raise SystemExit('preflight fixture does not execute workloads')\n"
    )
    command.chmod(command.stat().st_mode | stat.S_IXUSR)
    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
    return command
