"""Run the manual Discord webhook example with protected coordinator callbacks."""

from __future__ import annotations

# ruff: noqa: E402

import os
import sys
from pathlib import Path

REPO_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "examples" / "support.py").is_file()
)
HERE = Path(__file__).resolve().parent
PACKAGE_SOURCE = HERE / "src"
for path in (REPO_ROOT, PACKAGE_SOURCE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from examples.execution.agent_workers import run_example
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore


def main() -> None:
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE / "outputs"))
    os.environ["PYTHONPATH"] = (
        str(PACKAGE_SOURCE) + os.pathsep + os.environ.get("PYTHONPATH", "")
    )
    result = run_example(
        HERE / "pipeline.yaml",
        output_root,
        event_sinks=[
            {
                "name": "notifications.discord",
                "factory": {"_target_": "loom_discord.discord_event_sink"},
            }
        ],
    )
    admission = result.observation.admission
    run_uri = admission.run_uri
    failures = SQLitePerRunAuthorityStore(run_uri).read_event_sink_failures(run_uri)
    if admission.state.value != "SUCCEEDED":
        raise RuntimeError(f"example run did not succeed: {admission.state.value}")
    print(f"run_uri: {run_uri}")
    print(f"run_status: {admission.state.value}")
    print(f"notification_failure_count: {len(failures)}")
    print(
        "notification_status: " + ("no_failure_recorded" if not failures else "failed")
    )
    if failures:
        raise RuntimeError(failures[0].failure_message)


if __name__ == "__main__":
    main()
