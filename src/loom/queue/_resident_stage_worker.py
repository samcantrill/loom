"""Execution-only child process for one resident remote assignment."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import json
import os
from pathlib import Path
import time

from loom.pipeline.context import ProcessContainmentOwner
from loom.pipeline.execution.stage_worker import (
    execute_resident_stage_worker_request,
)
from loom.pipeline.stores.atomic import atomic_write_json

from ._remote_stage_execution import _ResidentAssignmentWorkspace
from .preparation import PREPARATION_INPUT_CONTEXT_ENV


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
    request = workspace.worker_request(resolve_shared=True)
    os.environ.pop(PREPARATION_INPUT_CONTEXT_ENV, None)
    preparation = workspace.preparation_context()
    if preparation is not None:
        os.environ[PREPARATION_INPUT_CONTEXT_ENV] = json.dumps(preparation, sort_keys=True, separators=(",", ":"))
    resolver: Callable[[object], object] | None = None
    container_execution = False
    shared_roots = None
    from .shared_execution import assignment_scope, materialize, execution_roots
    shared = assignment_scope(workspace.request().fingerprint)
    if shared is not None:
        profile = workspace.shared_launch_profile()
        container_execution = profile.container is not None
        roots = execution_roots(profile.shared_roots, container=container_execution)
        shared_roots = roots
        if workspace.request().preparation_input is None:
            def resolve_locations(value: object) -> object:
                return materialize(value, roots, container=container_execution)
            resolver = resolve_locations
    from ._shared_publication import worker_artifact_root
    artifact_root = worker_artifact_root(workspace, container=container_execution)
    result = execute_resident_stage_worker_request(
        worker_request=request,
        location_resolver=resolver,
        artifact_root=artifact_root,
        shared_roots=shared_roots,
        workspace_root=workspace_root,
        process_containment_owner=ProcessContainmentOwner.OUTER_BOUNDARY,
    )
    atomic_write_json(workspace_root / "worker-result.json", result.to_dict())
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through real process tests.
    raise SystemExit(main())
