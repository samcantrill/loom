"""SLURM composition helpers for Apptainer-backed commands."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import cast

from loom.pipeline.executors.apptainer import (
    ApptainerExecOptions,
    build_apptainer_exec_command,
)
from loom.pipeline.executors.containers import (
    ContainerEnvironment,
    ContainerOptions,
    ContainerResourceIntent,
    parse_container_options,
)
from loom.pipeline.executors.gpu_visibility import (
    CUDA_VISIBLE_DEVICES,
    project_apptainer_gpu_options,
    requested_gpu_count,
)
from loom.pipeline.resources import ResourceEntry, ResourceRequest
from loom.pipeline.runtime import ResourcePolicy
from loom.pipeline.runtime.capabilities import DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY
from loom.serialization import PlainData

from .errors import SlurmPlanningError
from .options import SlurmCommandArgv


def wrap_slurm_command_with_apptainer(
    command: SlurmCommandArgv,
    *,
    container_options: ContainerOptions | Mapping[str, object],
    apptainer_options: ApptainerExecOptions | Mapping[str, object] | None = None,
    resources: ResourceRequest | Mapping[str, ResourceEntry] | None = None,
) -> SlurmCommandArgv:
    """Wrap an existing SLURM command in deterministic Apptainer exec argv."""

    if not isinstance(command, SlurmCommandArgv):
        raise SlurmPlanningError("command must be SlurmCommandArgv")
    options = (
        apptainer_options
        if isinstance(apptainer_options, ApptainerExecOptions)
        else ApptainerExecOptions.from_dict(apptainer_options)
    )
    options = project_apptainer_gpu_options(options, resources)
    container = (
        container_options
        if isinstance(container_options, ContainerOptions)
        else parse_container_options(container_options)
    )
    entries = resources.entries if isinstance(resources, ResourceRequest) else resources
    if entries:
        descriptor = DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY.resolve("apptainer")
        container = replace(
            container,
            resources=ContainerResourceIntent(
                entries=entries,
                capabilities={
                    kind: descriptor.capability_for(kind) for kind in entries
                },
            ),
        )
    if requested_gpu_count(resources) > 0:
        environment = cast(ContainerEnvironment, container.environment)
        if (
            CUDA_VISIBLE_DEVICES in environment.variables
            or CUDA_VISIBLE_DEVICES in environment.required_host_variables
        ):
            raise SlurmPlanningError(
                "CUDA_VISIBLE_DEVICES is owned by Loom's SLURM GPU allocation projection"
            )
    apptainer_command = build_apptainer_exec_command(
        container_options=container,
        apptainer_options=options,
        worker_command=command.argv,
        # The outer allocation owns limits. Do not reapply its CPU/RAM cgroups
        # or invent a second GPU allocation in the inner container.
        resource_policy=ResourcePolicy(enforce=[]),
    )
    argv = tuple(apptainer_command.argv)
    return SlurmCommandArgv(
        launcher_argv=argv[:1],
        command_args=argv[1:],
        metadata=cast(
            Mapping[str, PlainData],
            {
                "container_runtime": "apptainer",
                "wrapped_command_argv": list(command.argv),
                "container_command": dict(apptainer_command.metadata),
                "redacted_argv": list(
                    cast(Sequence[str], apptainer_command.redacted_argv)
                ),
            },
        ),
    )


__all__ = ["wrap_slurm_command_with_apptainer"]
