"""Run the same pipeline locally and through subprocess workers."""

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
from loom.pipeline.stores import (
    LocalRunArtifactStore,
    path_to_run_uri,
)


HERE = Path(__file__).resolve().parent


def main() -> None:
    _configure_import_path()
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    config_path = HERE / "pipeline.yaml"
    local_uri = path_to_run_uri(run_root / f"local-{uuid4().hex[:8]}")
    subprocess_uri = path_to_run_uri(run_root / f"subprocess-{uuid4().hex[:8]}")
    service_uri = path_to_run_uri(run_root / f"subprocess-service-{uuid4().hex[:8]}")

    with started_authority_session(output_root) as authority:
        local = _run_cli(
            [
                "run",
                str(config_path),
                "--run-uri",
                local_uri,
                *authority.authority_args,
                "--format",
                "json",
            ]
        )
        subprocess = _run_cli(
            [
                "run",
                str(config_path),
                "--run-uri",
                subprocess_uri,
                "--executor",
                "subprocess",
                *authority.authority_args,
                "--format",
                "json",
            ]
        )
        service_run = _run_cli(
            [
                "run",
                str(config_path),
                "--run-uri",
                service_uri,
                "--executor",
                "subprocess",
                *authority.authority_args,
                "--format",
                "json",
            ]
        )

    store = LocalRunArtifactStore(run_root)
    provenance = store.stage_artifacts(subprocess_uri, "seed").read_stage_provenance()
    executor = None
    if provenance is not None:
        metadata = provenance.get("executor_metadata", {})
        if isinstance(metadata, dict):
            executor = metadata.get("executor")

    print(f"local_run_uri: {local_uri}")
    print(f"local_status: {local['result']['status']}")
    print(f"local_artifact_count: {local['result']['artifact_count']}")
    print(f"subprocess_run_uri: {subprocess_uri}")
    print(f"subprocess_status: {subprocess['result']['status']}")
    print(f"subprocess_artifact_count: {subprocess['result']['artifact_count']}")
    print(f"subprocess_seed_executor: {executor}")
    print(f"service_authority_run_uri: {service_uri}")
    print(f"service_authority_status: {service_run['result']['status']}")


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
