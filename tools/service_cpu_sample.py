"""Read-only Linux CPU-window measurement for explicitly selected owned services.

Use independently on each physical host. Samples contain process identity and
CPU deltas, never command lines, environment values or job contents. Child CPU
is excluded. No signal is sent and no service is started or stopped.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import time


def process_sample(pid: int) -> tuple[int, int]:
    proc = Path(f"/proc/{pid}")
    if proc.stat().st_uid != os.getuid():
        raise ValueError("selected process is not owned by the current user")
    # The parenthesized command can contain spaces and ')' characters.
    fields = (proc / "stat").read_text().rsplit(")", 1)[1].split()
    return int(fields[19]), int(fields[11]) + int(fields[12])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, action="append", required=True)
    parser.add_argument("--seconds", type=float, default=30)
    args = parser.parse_args()
    if not 0 < args.seconds <= 300 or any(pid <= 0 for pid in args.pid):
        parser.error("positive PIDs and a window in (0, 300] seconds are required")
    ticks_per_second = os.sysconf("SC_CLK_TCK")
    before = {pid: process_sample(pid) for pid in args.pid}
    start = time.monotonic()
    time.sleep(args.seconds)
    elapsed = time.monotonic() - start
    results = []
    for pid, (identity, ticks) in before.items():
        after_identity, after_ticks = process_sample(pid)
        if identity != after_identity or after_ticks < ticks:
            raise RuntimeError("selected process identity changed during measurement")
        cpu_seconds = (after_ticks - ticks) / ticks_per_second
        results.append({
            "pid": pid, "start_ticks": identity,
            "cpu_seconds": round(cpu_seconds, 3),
            "one_core_cpu_percent": round(100 * cpu_seconds / elapsed, 2),
        })
    print(json.dumps({
        "host": socket.gethostname(), "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "wall_seconds": round(elapsed, 3), "processes": results,
        "scope": "explicit owned service PIDs; child CPU excluded; read-only",
    }, sort_keys=True))


if __name__ == "__main__":
    main()
