"""Run a local pipeline with v4 runtime profile metadata."""

from __future__ import annotations

# ruff: noqa: E402

import os
import sys
from pathlib import Path
from typing import Any, cast
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
    WorkspaceIdentity,
    create_authority_client,
    path_to_run_uri,
)


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
    with started_authority_session(output_root) as authority:
        client = create_authority_client(authority.authority_config)
        workspace = client.create_workspace(
            WorkspaceIdentity(
                workspace_id=authority.workspace_id,
                root_uri=authority.workspace_root.resolve().as_uri(),
                metadata={"example": "execution.runtime-profile"},
            ),
            request_id="runtime-profile-workspace-create",
            service_generation=authority.generation,
        )
        if workspace.result is None or workspace.result.workspace is None:
            raise RuntimeError("expected authority workspace creation to succeed")
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
                *authority.authority_args,
                "--format",
                "json",
            ]
        )
    raw_metadata = LocalRunArtifactStore(run_root).read_runtime_metadata(run_uri)
    if raw_metadata is None:
        raise RuntimeError("runtime metadata was not written")
    metadata = cast(dict[str, Any], raw_metadata)

    print(f"run_uri: {run_uri}")
    print(f"preflight_status: {preflight['result']['status']}")
    print(f"run_status: {run['result']['status']}")
    print(f"runtime_executor: {metadata['executor']}")
    print(f"runtime_tags: {','.join(sorted(metadata['tags']))}")
    print(f"runtime_stage_count: {len(metadata['stages'])}")


def _run_cli(argv: list[str], *, expected: int = 0) -> dict[str, Any]:
    return run_cli_json(argv, expected=expected)


if __name__ == "__main__":
    main()
