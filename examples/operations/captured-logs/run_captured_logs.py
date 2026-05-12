"""Run a local pipeline with captured logs and inspect them through the CLI."""

from __future__ import annotations

# ruff: noqa: E402

import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "examples" / "support.py").is_file()
)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from examples.support import run_cli_json
from examples.support import started_authority_session
from loom.config import compose_config
from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.executors import LocalExecutor
from loom.pipeline.stores import path_to_run_uri


HERE = Path(__file__).resolve().parent


def main() -> None:
    sys.path.insert(0, str(HERE))
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    run_uri = path_to_run_uri(run_root / f"captured-logs-{uuid4().hex[:8]}")

    with started_authority_session(output_root) as authority:
        runner = PipelineRunner(
            run_store=create_authority_backed_serial_run_store(
                run_root,
                authority_config=authority.authority_config,
            ),
            executor=LocalExecutor(capture_stdout_stderr=True),
        )
        result = runner.run(
            RunRequest(config=compose_config(HERE / "pipeline.yaml"), run_uri=run_uri)
        )

    stdout_logs = _run_cli(
        [
            "logs",
            run_uri,
            "noisy",
            "--stream",
            "stdout",
            "--tail",
            "1",
            "--format",
            "json",
        ]
    )
    stderr_paths = _run_cli(
        ["logs", run_uri, "noisy", "--stream", "stderr", "--paths", "--format", "json"]
    )

    print(f"run_uri: {run_uri}")
    print(f"run_status: {result.status.name}")
    print(f"stdout_tail: {stdout_logs['result']['streams'][0]['content'].strip()}")
    print(f"stderr_path_available: {stderr_paths['result']['streams'][0]['available']}")


def _run_cli(argv: list[str], *, expected: int = 0) -> dict[str, Any]:
    return run_cli_json(argv, expected=expected)


if __name__ == "__main__":
    main()
