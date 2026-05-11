"""Run the successful local diagnostics workflow example."""

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
    sys.path.insert(0, str(HERE))
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    run_uri = path_to_run_uri(run_root / f"diagnostics-{uuid4().hex[:8]}")
    config_path = HERE / "pipeline.yaml"

    preflight = _run_cli(["preflight", str(config_path), "--format", "json"])
    with LocalAuthorityService.start() as service:
        authority_args = authority_config_to_cli_args(service.config())
        run = _run_cli(
            [
                "run",
                str(config_path),
                "--run-uri",
                run_uri,
                *authority_args,
                "--format",
                "json",
            ]
        )
        status = _run_cli(["status", run_uri, *authority_args, "--format", "json"])
    artifacts = _run_cli(["artifacts", "list", run_uri, "--format", "json"])
    artifact = _run_cli(
        ["artifacts", "show", run_uri, "summarize/summary", "--format", "json"]
    )

    print(f"run_uri: {run_uri}")
    print(f"preflight_status: {preflight['result']['status']}")
    print(f"run_status: {run['result']['status']}")
    print(f"stage_count: {len(status['result']['stages'])}")
    print(f"artifact_count: {artifacts['result']['artifact_count']}")
    print(f"shown_artifact: {artifact['result']['artifact']['artifact_id']}")


def _run_cli(argv: list[str], *, expected: int = 0) -> dict[str, Any]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = loom_main(argv, stdout=stdout, stderr=stderr)
    if code != expected:
        raise RuntimeError(
            f"loom {' '.join(argv)} exited {code}; stdout={stdout.getvalue()!r}; "
            f"stderr={stderr.getvalue()!r}"
        )
    output = stdout.getvalue()
    return json.loads(output) if output else {}


if __name__ == "__main__":
    main()
