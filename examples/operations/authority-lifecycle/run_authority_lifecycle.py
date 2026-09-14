"""Exercise the public authority supervisor lifecycle commands."""

from __future__ import annotations

# ruff: noqa: E402

import os
from pathlib import Path
import sys

REPO_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "examples" / "support.py").is_file()
)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from examples.support import run_cli_json, start_authority_session


HERE = Path(__file__).resolve().parent


def main() -> None:
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    authority = start_authority_session(output_root)
    try:
        start = authority.start_result
        status = authority.status()
        doctor = authority.doctor()
        initial_generation = authority.generation
        restarted = authority.restart()
        stop = authority.stop()
        # The session helper skips repeat calls, so exercise the CLI itself.
        repeated_stop = run_cli_json(
            [
                "authority",
                "stop",
                "--state-dir",
                str(authority.state_dir),
                "--workspace-root",
                str(authority.workspace_root),
                "--format",
                "json",
            ]
        )["result"]
        if (
            stop["process_state"] != "stopped"
            or repeated_stop["process_state"] != "stopped"
        ):
            raise RuntimeError(
                "authority stop did not confirm a completed, repeatable stop"
            )
    finally:
        if not authority.stopped:
            authority.stop()

    print("authority_lifecycle:")
    print(f"  endpoint: {start['endpoint']}")
    print(f"  readiness: {start['readiness']}")
    print(f"  registry_status: {status['registry_status']}")
    print(f"  process_state: {status['process_state']}")
    print(f"  doctor_ok: {doctor['ok']}")
    print(
        "  restarted_generation_changed: "
        f"{initial_generation != restarted['service_generation']}"
    )
    print(f"  stop_state: {stop['process_state']}")
    print(f"  repeated_stop_state: {repeated_stop['process_state']}")


if __name__ == "__main__":
    main()
