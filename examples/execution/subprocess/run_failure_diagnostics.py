"""Run a failing subprocess pipeline and inspect persisted diagnostics."""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from loom.cli.main import main as loom_main
from loom.pipeline.stores import authority_config_to_cli_args, path_to_run_uri
from loom.pipeline.stores.service_authority import LocalAuthorityService


HERE = Path(__file__).resolve().parent


def main() -> None:
    _configure_import_path()
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    run_uri = path_to_run_uri(run_root / f"subprocess-failure-{uuid4().hex[:8]}")
    config_path = HERE / "failing-pipeline.yaml"

    with LocalAuthorityService.start() as service:
        authority_args = authority_config_to_cli_args(service.config())
        run = _run_cli(
            [
                "run",
                str(config_path),
                "--run-uri",
                run_uri,
                "--executor",
                "subprocess",
                *authority_args,
                "--format",
                "json",
            ],
            expected=5,
        )
        status = _run_cli(["status", run_uri, *authority_args, "--format", "json"])
    logs = _run_cli(["logs", run_uri, "fail", "--stream", "stderr", "--format", "json"])

    failure = status["result"]["stages"][0]["failure"]
    if not isinstance(failure, dict):
        raise RuntimeError("expected persisted stage failure metadata")
    stderr_stream = logs["result"]["streams"][0]

    print(f"run_uri: {run_uri}")
    print(f"run_status: {run['result']['status']}")
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
