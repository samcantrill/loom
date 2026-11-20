"""Execution-only child process for one resident remote assignment."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import replace
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
from ._phase_timing import PhaseTimings, observe_phases
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
    workspace = _ResidentAssignmentWorkspace(
        agent_root, assignment_id, _allow_initialize=False,
    )
    gate = workspace_root / "run.grant"
    while not gate.is_file():
        time.sleep(0.01)
    from .shared_execution import assignment_scope, materialize, execution_roots

    retained = workspace.request()
    shared = assignment_scope(retained.fingerprint)
    if retained.submitted_execution is not None:
        from .submitted_execution import SUPPORTED_WORKER_CONTRACTS
        from .errors import QueueServiceError

        if retained.submitted_execution.worker_contract not in SUPPORTED_WORKER_CONTRACTS:
            raise QueueServiceError("submitted native worker contract is unsupported")
    timings = PhaseTimings()
    profile = None
    with observe_phases(timings.observe):
        # Validate this worker's namespace once before loading project inputs.
        # Image hashing remains the supervisor's new-launch responsibility.
        if shared is not None or retained.submitted_execution is not None:
            profile = timings.call("worker_input_qualification", workspace.shared_launch_profile)
        request = timings.call(
            "input_materialization", workspace.worker_request, resolve_shared=True, shared_profile=profile,
        )
        os.environ.pop(PREPARATION_INPUT_CONTEXT_ENV, None)
        preparation = timings.call(
            "preparation_materialization", workspace.preparation_context, shared_profile=profile,
        )
    if preparation is not None:
        os.environ[PREPARATION_INPUT_CONTEXT_ENV] = json.dumps(preparation, sort_keys=True, separators=(",", ":"))
    resolver: Callable[[object], object] | None = None
    container_execution = False
    shared_roots = None
    if shared is not None:
        assert profile is not None
        container_execution = profile.container is not None
        roots = execution_roots(profile.shared_roots, container=container_execution)
        shared_roots = roots
        if retained.preparation_input is None:
            def resolve_locations(value: object) -> object:
                return timings.call("location_materialization", materialize, value, roots, container=container_execution)
            resolver = resolve_locations
    from ._shared_publication import worker_artifact_root
    artifact_root = worker_artifact_root(workspace, container=container_execution)
    result = timings.call("worker_execution", execute_resident_stage_worker_request,
        worker_request=request,
        location_resolver=resolver,
        artifact_root=artifact_root,
        shared_roots=shared_roots,
        workspace_root=workspace_root,
        process_containment_owner=ProcessContainmentOwner.OUTER_BOUNDARY,
    )
    result = replace(result, executor_metadata={
        **result.executor_metadata, "native_timings": timings.payload(),
    })
    atomic_write_json(
        workspace_root / "worker-result.json", result.to_dict(),
        durability=workspace.durable_files,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through real process tests.
    raise SystemExit(main())
