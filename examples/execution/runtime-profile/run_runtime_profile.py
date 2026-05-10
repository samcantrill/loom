"""Run a local pipeline with v4 runtime profile metadata."""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from loom.cli.main import main as loom_main
from loom.pipeline.stores import LocalRunArtifactStore, path_to_run_uri


HERE = Path(__file__).resolve().parent


def main() -> None:
    sys.path.insert(0, str(HERE))
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    run_uri = path_to_run_uri(run_root / f"runtime-profile-{uuid4().hex[:8]}")
    config_path = HERE / "pipeline.yaml"

    preflight = _run_cli(
        [
            "preflight",
            str(config_path),
            "--check",
            "runtime",
            "--check",
            "resources",
            "--format",
            "json",
        ]
    )
    run = _run_cli(
        [
            "run",
            str(config_path),
            "--run-uri",
            run_uri,
            "--tag",
            "invocation=cli",
            "--note",
            "runtime example executed",
            "--format",
            "json",
        ]
    )
    metadata = LocalRunArtifactStore(run_root).read_runtime_metadata(run_uri)
    if metadata is None:
        raise RuntimeError("runtime metadata was not written")

    print(f"run_uri: {run_uri}")
    print(f"preflight_status: {preflight['result']['status']}")
    print(f"run_status: {run['result']['status']}")
    print(f"runtime_executor: {metadata['executor']}")
    print(f"runtime_tags: {','.join(sorted(metadata['tags']))}")
    print(f"runtime_stage_count: {len(metadata['stages'])}")


def _run_cli(argv: list[str], *, expected: int = 0) -> dict[str, object]:
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
