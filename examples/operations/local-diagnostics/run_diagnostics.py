"""Run the successful local diagnostics workflow example."""

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
    sys.path.insert(0, str(HERE))
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    run_uri = path_to_run_uri(run_root / f"diagnostics-{uuid4().hex[:8]}")
    config_path = HERE / "pipeline.yaml"

    preflight = _run_cli(["preflight", str(config_path), "--format", "json"])
    with started_authority_session(output_root) as authority:
        run = _run_cli(
            [
                "run",
                str(config_path),
                "--run-uri",
                run_uri,
                *authority.authority_args,
                "--format",
                "json",
            ]
        )
        status = _run_cli(
            ["status", run_uri, *authority.authority_args, "--format", "json"]
        )
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
    return run_cli_json(argv, expected=expected)


if __name__ == "__main__":
    main()
