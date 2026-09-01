"""Execution-only child process for one resident remote assignment."""

from __future__ import annotations

import argparse
from pathlib import Path
import time

from loom.pipeline.context import ProcessContainmentOwner
from loom.pipeline.execution.stage_worker import (
    execute_resident_stage_worker_request,
)
from loom.pipeline.stores.atomic import atomic_write_json

from ._remote_stage_execution import _ResidentAssignmentWorkspace


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--workspace", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    workspace_root = Path(arguments.workspace).resolve()
    assignment_id = workspace_root.name
    agent_root = workspace_root.parent.parent
    workspace = _ResidentAssignmentWorkspace(agent_root, assignment_id)
    gate = workspace_root / "run.grant"
    while not gate.is_file():
        time.sleep(0.01)
    request = workspace.worker_request()
    result = execute_resident_stage_worker_request(
        worker_request=request,
        workspace_root=workspace_root,
        process_containment_owner=ProcessContainmentOwner.OUTER_BOUNDARY,
    )
    atomic_write_json(workspace_root / "worker-result.json", result.to_dict())
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through real process tests.
    raise SystemExit(main())
