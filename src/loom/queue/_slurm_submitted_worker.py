"""Allocation-owned launch and execution of one immutable submitted workload."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
from typing import Mapping, cast

from loom.pipeline.context import ProcessContainmentOwner
from loom.pipeline.execution.models import StageWorkerResult
from loom.pipeline.execution.stage_worker import execute_resident_stage_worker_request
from loom.pipeline.executors.apptainer.commands import ApptainerExecCommand
from loom.pipeline.resources import ResourceRequest
from loom.pipeline.runtime.resource_policy import ResourcePolicy
from loom.pipeline.stores.atomic import atomic_write_json
from loom.serialization import PlainData

from ._submitted_container_policy import SubmittedContainerPolicy
from .errors import QueueConflictError, QueueServiceError
from .slurm_ready_stage import SlurmBootstrapWorkspace


def submitted_command(
    workspace: SlurmBootstrapWorkspace,
    policy: SubmittedContainerPolicy,
    *,
    agent_id: str,
    fence: str,
    allocation_environment: Mapping[str, str],
) -> ApptainerExecCommand:
    """Verify a new launch and project only its allocation and authorized mounts."""
    from ._container_worker import (
        qualify_shared_worker_inputs,
        project_container_worker,
    )
    from ._shared_publication import worker_artifact_root
    from ._temporary_storage import prepare_assignment_storage
    from .shared_execution import assignment_scope
    from .submitted_execution import assignment_binding

    request = workspace.delivery()
    binding = assignment_binding(request.fingerprint)
    if binding is None:
        raise QueueConflictError("SLURM submitted launch requires an image binding")
    execution, capability = binding
    if not policy.runtime_options["cleanenv"]:
        raise QueueServiceError(
            "submitted SLURM workers require a clean container environment"
        )
    profile = policy.launch_profile(
        execution, workspace=workspace.root, selected_capability=capability
    )
    workspace.persist_execution_binding(agent_id=agent_id, fence=fence, profile=profile)
    worker_artifact_root(workspace)
    prepare_assignment_storage(profile, workspace=workspace.root, agent_id=agent_id)
    qualify_shared_worker_inputs(profile, request, agent_id=agent_id)
    workspace.accept_inputs(shared_roots=profile.shared_roots)
    resources = ResourceRequest.from_dict(request.resolved_runtime["resources"])
    # CPU, memory and walltime are delegated to the outer Slurm allocation.
    # CUDA visibility is still projected into Apptainer's clean environment.
    gpu = resources.entries.get("gpu")
    controls = ResourcePolicy(
        account_for="all", enforce=("gpu",) if gpu is not None and gpu.amount else ()
    )
    runtime = {
        **request.resolved_runtime,
        "resource_policy": controls.to_dict(),
        "resource_selection": controls.select(resources.entries),
    }
    environment = dict(policy.environment)
    if gpu is not None and gpu.amount:
        if "CUDA_VISIBLE_DEVICES" in policy.environment:
            raise QueueServiceError("SLURM allocation owns CUDA visibility")
        if "CUDA_VISIBLE_DEVICES" in allocation_environment:
            environment["CUDA_VISIBLE_DEVICES"] = allocation_environment[
                "CUDA_VISIBLE_DEVICES"
            ]
    worker = (
        execution.python_executable,
        "-m",
        "loom.queue._slurm_submitted_worker",
        "--workspace",
        str(workspace.root),
    )
    preparation = request.preparation_input
    return cast(
        ApptainerExecCommand,
        project_container_worker(
            profile,
            workspace=workspace.root,
            worker=worker,
            environment=environment,
            runtime=runtime,
            shared_scope=assignment_scope(request.fingerprint),
            shared_snapshot=None if preparation is None else preparation.input_receipt,
            agent_id=agent_id,
            assignment=request,
        ),
    )


def run_submitted_stage(
    workspace: SlurmBootstrapWorkspace,
    policy: SubmittedContainerPolicy,
    *,
    agent_id: str,
    fence: str,
) -> StageWorkerResult:
    """Launch once after the coordinator consumes the job's execution permit."""
    command = submitted_command(
        workspace,
        policy,
        agent_id=agent_id,
        fence=fence,
        allocation_environment=os.environ,
    )
    logs = workspace.root / "logs"
    logs.mkdir(exist_ok=True)
    # Bootstrap credentials/configuration and inherited container injection
    # variables never become workload environment. The command owns cleanenv.
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(
            ("LOOM_", "APPTAINERENV_", "SINGULARITYENV_", "APPTAINER_", "SINGULARITY_")
        )
    }
    with (
        (logs / "container-stdout.log").open("ab") as stdout,
        (logs / "container-stderr.log").open("ab") as stderr,
    ):
        completed = subprocess.run(
            command.argv,
            cwd=workspace.root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            check=False,
        )
    if completed.returncode:
        raise QueueServiceError(
            f"submitted SLURM worker exited with {completed.returncode}"
        )
    result = StageWorkerResult.from_dict(
        json.loads((workspace.root / "worker-result.json").read_text())
    )
    return replace(
        result,
        executor_metadata={
            **result.executor_metadata,
            "container_runtime": "apptainer",
            "gpu_visibility": cast(PlainData, command.metadata["gpu_visibility"]),
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--workspace", required=True)
    path = Path(parser.parse_args(argv).workspace).resolve()
    workspace = SlurmBootstrapWorkspace(path.parent.parent, path.name)
    profile = workspace.shared_launch_profile()
    request = workspace.delivery()
    from .submitted_execution import SUPPORTED_WORKER_CONTRACTS

    if (
        request.submitted_execution is None
        or request.submitted_execution.worker_contract not in SUPPORTED_WORKER_CONTRACTS
    ):
        raise QueueServiceError("submitted SLURM worker contract is unsupported")
    from .shared_execution import execution_roots, materialize
    from ._remote_stage_execution import _preparation_worker_context
    from .preparation import PREPARATION_INPUT_CONTEXT_ENV
    from ._shared_publication import worker_artifact_root

    roots = execution_roots(profile.shared_roots, container=True)
    preparation = _preparation_worker_context(request, profile, workspace.root)
    os.environ.pop(PREPARATION_INPUT_CONTEXT_ENV, None)
    if preparation is not None:
        os.environ[PREPARATION_INPUT_CONTEXT_ENV] = json.dumps(
            preparation, sort_keys=True, separators=(",", ":")
        )
    result = execute_resident_stage_worker_request(
        worker_request=workspace.worker_request(shared_roots=roots),
        workspace_root=workspace.root,
        process_containment_owner=ProcessContainmentOwner.OUTER_BOUNDARY,
        location_resolver=None
        if preparation is not None
        else lambda value: materialize(value, roots, container=True),
        artifact_root=worker_artifact_root(workspace, container=True),
        shared_roots=roots,
    )
    atomic_write_json(workspace.root / "worker-result.json", result.to_dict())
    return 0


if __name__ == "__main__":  # pragma: no cover - physical runtime qualification.
    raise SystemExit(main())
