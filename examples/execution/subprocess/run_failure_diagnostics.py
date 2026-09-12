"""Run a failing subprocess pipeline and inspect persisted diagnostics."""

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
from loom.pipeline.stores import path_to_run_uri


HERE = Path(__file__).resolve().parent


def main() -> None:
    _configure_import_path()
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    run_uri = path_to_run_uri(run_root / f"subprocess-failure-{uuid4().hex[:8]}")
    config_path = HERE / "failing-pipeline.yaml"

    with started_authority_session(output_root) as authority:
        from weave import compose_config
        from loom.pipeline.execution import PipelineRunner, RunRequest, RuntimeServices, create_authority_backed_serial_run_store
        from loom.pipeline.runtime import merge_config_run_options
        from loom.pipeline.executors import SubprocessExecutor
        composed = compose_config(str(config_path))
        execution_options = merge_config_run_options(composed.resolved, explicit={"run_uri": run_uri, "executor": 'subprocess'})
        execution_store = create_authority_backed_serial_run_store(run_root, authority_config=authority.authority_config)
        run = PipelineRunner(services=RuntimeServices.from_legacy(execution_store), executor=SubprocessExecutor(worker_results=execution_store)).run(RunRequest(config=composed, options=execution_options))
        status = _run_cli(
            ["status", run_uri, *authority.authority_args, "--format", "json"]
        )
    logs = _run_cli(["logs", run_uri, "fail", "--stream", "stderr", "--format", "json"])

    failure = status["result"]["stages"][0]["failure"]
    if not isinstance(failure, dict):
        raise RuntimeError("expected persisted stage failure metadata")
    stderr_stream = logs["result"]["streams"][0]

    print(f"run_uri: {run_uri}")
    print(f"run_status: {run.status.value}")
    print(f"failure_executor: {failure['executor']}")
    print(f"failure_exit_code: {failure['exit_code']}")
    print(f"stderr_available: {stderr_stream['available']}")


def _configure_import_path() -> None:
    sys.path.insert(0, str(HERE))
    existing = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = (
        str(HERE) if not existing else str(HERE) + os.pathsep + existing
    )


def _run_cli(argv: list[str], *, expected: int = 0) -> dict[str, Any]:
    return run_cli_json(argv, expected=expected)


if __name__ == "__main__":
    main()
