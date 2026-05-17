"""SLURM composition helpers for Apptainer-backed commands."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from loom.pipeline.executors.apptainer import (
    ApptainerExecOptions,
    build_apptainer_exec_command,
)
from loom.pipeline.executors.containers import (
    ContainerBuildOptions,
    ContainerBuildCommandProjection,
    ContainerBuildEvidence,
    ContainerBuildFailure,
    ContainerBuildKeySummary,
    ContainerBuildOutputKind,
    ContainerBuildOutputRef,
    ContainerBuildResult,
    ContainerBuildRuntime,
    ContainerBuildStatus,
    ContainerBuildTarget,
    ContainerMount,
    ContainerMountMode,
    ContainerOptions,
    LocalContainerBuildService,
    container_build_output_identity,
    parse_container_build_options,
    parse_container_options,
)
from loom.pipeline.stores.run_store import LocalRunStorePaths
from loom.serialization import PlainData

from .errors import SlurmPlanningError
from .options import SlurmCommandArgv


@dataclass(frozen=True, slots=True)
class SlurmResolvedContainerTarget:
    """Resolved container namespace plus optional build result evidence."""

    container_options: Mapping[str, PlainData]
    build_result: ContainerBuildResult | None = None


def wrap_slurm_command_with_apptainer(
    command: SlurmCommandArgv,
    *,
    container_options: ContainerOptions | Mapping[str, object],
    apptainer_options: ApptainerExecOptions | Mapping[str, object] | None = None,
) -> SlurmCommandArgv:
    """Wrap an existing SLURM command in deterministic Apptainer exec argv."""

    if not isinstance(command, SlurmCommandArgv):
        raise SlurmPlanningError("command must be SlurmCommandArgv")
    apptainer_command = build_apptainer_exec_command(
        container_options=container_options,
        apptainer_options=apptainer_options,
        worker_command=command.argv,
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


def prepare_slurm_container_options(
    container_options: ContainerOptions | Mapping[str, object],
    *,
    run_store: object,
    run_uri: str,
) -> ContainerOptions:
    """Parse container options and inject required SLURM path-parity mounts."""

    container = (
        container_options
        if isinstance(container_options, ContainerOptions)
        else parse_container_options(container_options)
    )
    if not isinstance(run_store, LocalRunStorePaths):
        raise SlurmPlanningError(
            "SLURM Apptainer composition requires local run-store path helpers"
        )

    mounts = list(cast(tuple[ContainerMount, ...], container.mounts))
    for path in (
        _local_store_path(run_store.local_run_dir(run_uri), kind="run_dir"),
        _local_store_path(
            run_store.local_artifact_root(run_uri),
            kind="artifact_root",
        ),
    ):
        existing = next((mount for mount in mounts if mount.target == path), None)
        if existing is None:
            mounts.append(
                ContainerMount(
                    source=path,
                    target=path,
                    mode=ContainerMountMode.READ_WRITE,
                )
            )
            continue
        mode = cast(ContainerMountMode, existing.mode)
        if existing.source != path or mode is not ContainerMountMode.READ_WRITE:
            raise SlurmPlanningError(
                "SLURM Apptainer required path-parity mount must be read-write"
            )
    prepared = ContainerOptions(
        image=container.image,
        workdir=container.workdir,
        mounts=tuple(mounts),
        environment=container.environment,
        resources=container.resources,
    )
    invalid = [summary.to_dict() for summary in prepared.path_parity_summaries() if not summary.ok]
    if invalid:
        raise SlurmPlanningError("SLURM Apptainer path parity validation failed")
    return prepared


def resolve_slurm_container_target(
    container_options: Mapping[str, object],
    *,
    build_options: ContainerBuildOptions | Mapping[str, object] | None,
    build_service: LocalContainerBuildService,
    requested_by: str,
) -> SlurmResolvedContainerTarget:
    """Resolve ``container.target`` into an Apptainer SIF image reference."""

    raw_container = _mapping(container_options, path="adapter_options.container")
    target_name = raw_container.get("target")
    if target_name is None:
        return SlurmResolvedContainerTarget(
            container_options=cast(Mapping[str, PlainData], dict(raw_container)),
        )
    if not isinstance(target_name, str) or not target_name:
        raise SlurmPlanningError("adapter_options.container.target must be non-empty")
    if "image" in raw_container:
        raise SlurmPlanningError(
            "adapter_options.container cannot set both image and target"
        )

    targets = parse_container_build_options(build_options).targets
    target = cast(Mapping[str, ContainerBuildTarget], targets).get(target_name)
    if target is None:
        raise SlurmPlanningError(
            f"container build target {target_name!r} is not defined"
        )
    runtime = cast(ContainerBuildRuntime, target.runtime)
    if runtime is not ContainerBuildRuntime.APPTAINER:
        raise SlurmPlanningError(
            "SLURM Apptainer composition requires an apptainer build target"
        )

    result = build_service.build_target(target, requested_by=requested_by)
    if cast(ContainerBuildStatus, result.status) is ContainerBuildStatus.FAILED:
        failure = cast(ContainerBuildFailure | None, result.failure)
        message = (
            "container build target failed"
            if failure is None
            else f"container build target failed: {failure.message}"
        )
        raise SlurmPlanningError(message)
    output = cast(ContainerBuildOutputRef | None, result.output)
    if output is None:
        raise SlurmPlanningError(
            f"container build target {target_name!r} did not produce an output"
        )
    if cast(ContainerBuildOutputKind, output.kind) is not ContainerBuildOutputKind.APPTAINER_SIF:
        raise SlurmPlanningError(
            "SLURM Apptainer composition requires an apptainer_sif output"
        )

    resolved = dict(raw_container)
    resolved.pop("target", None)
    resolved["image"] = {"reference": container_build_output_identity(output)}
    return SlurmResolvedContainerTarget(
        container_options=cast(Mapping[str, PlainData], resolved),
        build_result=result,
    )


def container_build_results_metadata(
    results: Sequence[ContainerBuildResult],
) -> tuple[Mapping[str, PlainData], ...]:
    """Return redacted build-result summaries for SLURM metadata."""

    summaries: list[Mapping[str, PlainData]] = []
    for result in results:
        output = cast(ContainerBuildOutputRef | None, result.output)
        summaries.append(
            {
                "target_name": result.target_name,
                "status": cast(ContainerBuildStatus, result.status).value,
                "output": None if output is None else output.to_redacted_metadata(),
                "build_key": None
                if result.build_key is None
                else cast(ContainerBuildKeySummary, result.build_key).to_dict(),
                "command": None
                if result.command is None
                else cast(ContainerBuildCommandProjection, result.command).to_dict(),
                "evidence": None
                if result.evidence is None
                else cast(ContainerBuildEvidence, result.evidence).to_dict(),
            }
        )
    return tuple(summaries)


def _local_store_path(path: Path, *, kind: str) -> str:
    normalized = Path(path)
    if not normalized.is_absolute():
        raise SlurmPlanningError(f"SLURM Apptainer {kind} path is not absolute")
    return str(normalized)


def _mapping(value: object, *, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SlurmPlanningError(f"{path} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise SlurmPlanningError(f"{path} must use string keys")
    return cast(Mapping[str, object], value)


__all__ = [
    "SlurmResolvedContainerTarget",
    "container_build_results_metadata",
    "prepare_slurm_container_options",
    "resolve_slurm_container_target",
    "wrap_slurm_command_with_apptainer",
]
