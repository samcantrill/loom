"""Create and inspect a synthetic submitted run without scheduler queries."""

from __future__ import annotations

# ruff: noqa: E402

import json
import os
from pathlib import Path
import sys
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
from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.status import RunStatus, RunStatusRecord, StageStatus, StageStatusRecord
from loom.pipeline.stores import path_to_run_uri
from loom.pipeline.submitted import SubmittedOperationRecord, SubmittedOperationState


HERE = Path(__file__).resolve().parent
CREATED_AT = "2026-05-08T00:00:00Z"
UPDATED_AT = "2026-05-08T00:00:03Z"


def main() -> None:
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    run_uri = path_to_run_uri(run_root / f"submitted-status-{uuid4().hex[:8]}")
    submission_id = "example-submitted"
    manifest_relative_path = f"slurm/submissions/{submission_id}/manifest.json"

    with started_authority_session(output_root) as authority:
        store = create_authority_backed_serial_run_store(
            run_root,
            authority_config=authority.authority_config,
        )
        store.create_run(run_uri, metadata={"example": "operations.submitted-status"})
        store.write_run_status(
            run_uri,
            RunStatusRecord(
                run_uri=run_uri,
                status=RunStatus.SUBMITTED,
                created_at=CREATED_AT,
                updated_at=UPDATED_AT,
                message="submitted to an external scheduler",
            ),
        )
        for stage_name in ("seed", "summarize"):
            store.write_stage_status(
                run_uri,
                stage_name,
                StageStatusRecord(
                    run_uri=run_uri,
                    stage_name=stage_name,
                    status=StageStatus.SUBMITTED,
                    attempt=1,
                    updated_at=UPDATED_AT,
                    message="accepted by scheduler",
                ),
            )
        manifest_path = store.local_generated_artifact_path(
            run_uri,
            manifest_relative_path,
        )
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "example": "operations.submitted-status",
                    "note": "ordinary status only reports the pointer to this manifest",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        store.write_submitted_operation(
            run_uri,
            SubmittedOperationRecord(
                run_uri=run_uri,
                submission_id=submission_id,
                backend="slurm",
                mode="slurm-afterok",
                created_at=CREATED_AT,
                updated_at=UPDATED_AT,
                state=SubmittedOperationState.SUBMITTED,
                manifest_relative_path=manifest_relative_path,
                summary_counts={"submitted": 2, "active": 2},
            ),
        )

        payload = run_cli_json(
            ["status", run_uri, *authority.authority_args, "--format", "json"]
        )
    result = require_mapping(payload["result"])
    operation = require_mapping(result["submitted_operations"][0])
    stages = require_mappings(result["stages"])

    print("submitted_status:")
    print(f"  run_uri: {run_uri}")
    print(f"  run_status: {result['status']}")
    print(f"  stage_statuses: {','.join(stage['status'] for stage in stages)}")
    print(f"  submission_id: {operation['submission_id']}")
    print(f"  backend: {operation['backend']}")
    print(f"  mode: {operation['mode']}")
    print(f"  active: {operation['active']}")
    print(f"  manifest: {operation['manifest_relative_path']}")
    print(f"  summary_counts: {format_counts(operation['summary_counts'])}")

def format_counts(value: object) -> str:
    counts = require_mapping(value)
    return ",".join(f"{key}={counts[key]}" for key in sorted(counts))


def require_mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError("expected a mapping")
    return value


def require_mappings(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise RuntimeError("expected a list")
    output: list[dict[str, Any]] = []
    for item in value:
        output.append(require_mapping(item))
    return output


if __name__ == "__main__":
    main()
