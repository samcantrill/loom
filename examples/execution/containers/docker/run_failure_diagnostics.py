"""Run a failing Docker pipeline and inspect persisted diagnostics."""

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
from fake_docker import activate_fake_docker
from fake_docker import read_fake_docker_log
from loom.pipeline.stores import path_to_run_uri


HERE = Path(__file__).resolve().parent


def main() -> None:
    _configure_import_path()
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    run_root.mkdir(parents=True, exist_ok=True)
    fake_docker = activate_fake_docker(output_root)
    config_path = HERE / "failing-pipeline.yaml"
    run_uri = path_to_run_uri(run_root / f"docker-failure-{uuid4().hex[:8]}")

    with started_authority_session(output_root) as authority:
        run = _run_cli(
            [
                "run",
                str(config_path),
                "--run-uri",
                run_uri,
                "--executor",
                "docker",
                *authority.authority_args,
                "--format",
                "json",
            ],
            expected=5,
        )
        status = _run_cli(
            ["status", run_uri, *authority.authority_args, "--format", "json"]
        )
    logs = _run_cli(["logs", run_uri, "fail", "--stream", "stderr", "--format", "json"])

    failure = status["result"]["stages"][0]["failure"]
    if not isinstance(failure, dict):
        raise RuntimeError("expected persisted Docker stage failure metadata")
    stderr_stream = logs["result"]["streams"][0]
    calls = [
        record
        for record in read_fake_docker_log(fake_docker.log_path)
        if record.get("operation") == "run"
    ]

    print(f"run_uri: {run_uri}")
    print(f"run_status: {run['result']['status']}")
    print(f"failure_executor: {failure['executor']}")
    print(f"failure_exit_code: {failure['exit_code']}")
    print(f"stderr_available: {stderr_stream['available']}")
    print(f"fake_docker_call_count: {len(calls)}")


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
