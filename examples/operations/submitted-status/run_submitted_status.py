"""Create and inspect a synthetic submitted run without scheduler queries."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from loom.cli.main import main as loom_main
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
    store = create_authority_backed_serial_run_store(run_root)
    run_uri = path_to_run_uri(run_root / f"submitted-status-{uuid4().hex[:8]}")
    submission_id = "example-submitted"
    manifest_relative_path = f"slurm/submissions/{submission_id}/manifest.json"

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
    manifest_path = store.local_generated_artifact_path(run_uri, manifest_relative_path)
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

    payload = run_cli_json(["status", run_uri, "--format", "json"])
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


def run_cli_json(argv: list[str], *, expected: int = 0) -> dict[str, Any]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = loom_main(argv, stdout=stdout, stderr=stderr)
    if code != expected:
        raise RuntimeError(
            f"loom {' '.join(argv)} exited {code}; stdout={stdout.getvalue()!r}; "
            f"stderr={stderr.getvalue()!r}"
        )
    if stderr.getvalue():
        raise RuntimeError(f"unexpected stderr from loom {' '.join(argv)}")
    return require_mapping(json.loads(stdout.getvalue()))


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
