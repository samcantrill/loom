"""Run the authenticated remote-agent management journey in this checkout.

The journey generates its own short-lived CA and starts a loopback mutual-TLS
server. It covers registration and policy rechecks, with client and daemon
shutdown asserted by the invoked integration journey.
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
            "tests/integration/queue/test_agent_session_transport.py::test_loopback_mtls_derives_credential_and_rechecks_live_policy",
        ],
        cwd=checkout,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
