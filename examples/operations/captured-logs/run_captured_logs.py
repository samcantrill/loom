"""Run a local pipeline with captured logs and inspect them through the CLI."""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from loom.cli.main import main as loom_main
from loom.config import compose_config
from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.executors import LocalExecutor
from loom.pipeline.stores import path_to_run_uri
from loom.pipeline.stores.service_authority import LocalAuthorityService


HERE = Path(__file__).resolve().parent


def main() -> None:
    sys.path.insert(0, str(HERE))
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    run_uri = path_to_run_uri(run_root / f"captured-logs-{uuid4().hex[:8]}")

    with LocalAuthorityService.start() as service:
        runner = PipelineRunner(
            run_store=create_authority_backed_serial_run_store(
                run_root,
                authority_config=service.config(),
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
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = loom_main(argv, stdout=stdout, stderr=stderr)
    if code != expected:
        raise RuntimeError(
            f"loom {' '.join(argv)} exited {code}; stdout={stdout.getvalue()!r}; "
            f"stderr={stderr.getvalue()!r}"
        )
    return json.loads(stdout.getvalue())


if __name__ == "__main__":
    main()
