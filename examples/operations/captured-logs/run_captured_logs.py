"""Run a local pipeline with captured logs and inspect them through the CLI."""

from __future__ import annotations

# ruff: noqa: E402

import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "examples" / "support.py").is_file()
)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from examples.support import run_cli_json
from loom.artifacts import ArtifactRef
from examples.execution.agent_workers import run_example, worker_records


HERE = Path(__file__).resolve().parent


def main() -> None:
    sys.path.insert(0, str(HERE))
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    result = run_example(HERE / "pipeline.yaml", output_root, run_root=run_root)
    run_uri = result.observation.admission.run_uri

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
    print(f"run_status: {result.observation.admission.state.name}")
    outputs = worker_records(result)["noisy"].outputs
    print(f"output_names: {','.join(sorted(outputs))}")
    print(
        "outputs_are_refs: "
        f"{all(isinstance(ref, ArtifactRef) for ref in outputs.values())}"
    )
    print(f"stdout_tail: {stdout_logs['result']['streams'][0]['content'].strip()}")
    print(f"stderr_path_available: {stderr_paths['result']['streams'][0]['available']}")


def _run_cli(argv: list[str], *, expected: int = 0) -> dict[str, Any]:
    return run_cli_json(argv, expected=expected)


if __name__ == "__main__":
    main()
