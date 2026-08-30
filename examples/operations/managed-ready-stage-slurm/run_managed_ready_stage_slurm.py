"""Run the fake-gateway ready-stage SLURM recovery journey in this checkout.

It drives every durable rejection, restart, result, and release arrow with the
repository fake command gateway; no SLURM service or credentials are required.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def main() -> int:
    checkout = Path(__file__).resolve().parents[3]
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/integration/queue/test_slurm_ready_stage.py::test_definite_slurm_rejection_restarts_after_every_release_arrow",
        ],
        cwd=checkout,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
