"""Installed container bindings for the resident execution-only boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
import re
from typing import TYPE_CHECKING, cast

from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data

if TYPE_CHECKING:
    from ._agent_process_supervisor import ResidentWorkerLaunchProfile


def container_binding(
    value: Mapping[str, PlainData] | None,
) -> Mapping[str, PlainData] | None:
    if value is None:
        return None
    from loom.pipeline.executors.containers import (
        ContainerImageReference,
        parse_container_options,
    )

    data = thaw_plain_data(freeze_plain_data(value, path="installed container"))
    if not isinstance(data, Mapping) or set(data) != {
        "kind",
        "container",
        "options",
        "python_executable",
        "daemon_endpoint",
    }:
        raise ValueError("installed container binding is invalid")
    if data["kind"] not in {"docker", "apptainer"}:
        raise ValueError("installed container runtime is unsupported")
    if not isinstance(data["python_executable"], str) or not data["python_executable"]:
        raise ValueError("installed container Python is required")
    container = parse_container_options(data["container"])
    options = data["options"]
    if not isinstance(options, Mapping) or not isinstance(options.get("command"), str):
        raise ValueError("installed container requires an explicit runtime executable")
    if not Path(cast(str, options["command"])).is_absolute():
        raise ValueError("installed container runtime executable must be absolute")
    if data["kind"] == "docker":
        from loom.pipeline.executors.docker.commands import DockerOptions

        DockerOptions.from_dict(options)
        if not isinstance(data["daemon_endpoint"], str) or not data["daemon_endpoint"]:
            raise ValueError("Docker requires an explicit daemon endpoint")
        image = cast(ContainerImageReference, container.image).reference
        if re.fullmatch(r"(?:[^\s]+@)?sha256:[0-9a-f]{64}", image) is None:
            raise ValueError("Docker requires an installed immutable image reference")
    else:
        from loom.pipeline.executors.apptainer.commands import ApptainerExecOptions

        ApptainerExecOptions.from_dict(options)
        if data["daemon_endpoint"] is not None:
            raise ValueError("Apptainer has no daemon endpoint")
        if not Path(
            cast(ContainerImageReference, container.image).reference
        ).is_absolute():
            raise ValueError("Apptainer requires an installed absolute image path")
    return cast(Mapping[str, PlainData], data)


def build_container_worker(
    profile: ResidentWorkerLaunchProfile,
    *,
    workspace: Path,
    worker: Sequence[str],
    environment: Mapping[str, str],
    runtime: Mapping[str, PlainData] | None = None,
):
    """Reuse container resource projection with assignment-owned path parity."""
    from loom.pipeline.executors.containers import (
        ContainerEnvironment,
        ContainerMount,
        ContainerMountMode,
        ContainerResourceIntent,
        parse_container_options,
    )

    binding = profile.container
    assert binding is not None
    container = parse_container_options(binding["container"])
    required = {
        str(profile.project_root): "ro",
        str(workspace.parent.parent): "rw",
        **{
            str(path): "ro"
            for path in profile.preparation_shared_roots.values()
            if runtime is not None or path.exists()
        },
    }
    mounts = {
        mount.target: mount
        for mount in cast(tuple[ContainerMount, ...], container.mounts)
    }
    for path, mode in required.items():
        existing = mounts.get(path)
        if existing is not None and (
            existing.source != path
            or cast(ContainerMountMode, existing.mode).value != mode
        ):
            raise ValueError(
                "installed container mount conflicts with worker path parity"
            )
        mounts[path] = ContainerMount(source=path, target=path, mode=mode)
    declared = cast(ContainerEnvironment, container.environment)
    merged = {**declared.variables, **environment}
    # Host virtualenv PATH must not select Python outside the configured image.
    if "PATH" not in profile.environment:
        if "PATH" in declared.variables:
            merged["PATH"] = declared.variables["PATH"]
        else:
            merged.pop("PATH", None)
    if runtime is not None and binding["kind"] == "apptainer":
        selection_data = runtime.get("resource_selection")
        if isinstance(selection_data, Mapping) and "gpu" in cast(
            Sequence[str], selection_data.get("enforce", ())
        ):
            if "CUDA_VISIBLE_DEVICES" in declared.variables:
                raise ValueError(
                    "authored CUDA visibility conflicts with selected GPU enforcement"
                )
            merged.pop("CUDA_VISIBLE_DEVICES", None)
    container = replace(
        container,
        workdir=str(profile.project_root),
        mounts=tuple(mounts.values()),
        environment=ContainerEnvironment(
            variables=merged, required_host_variables=declared.required_host_variables
        ),
    )
    policy = selection = None
    if runtime is not None and "resources" in runtime:
        from loom.pipeline.resources import ResourceRequest

        resources = ResourceRequest.from_dict(runtime["resources"])
        from loom.pipeline.runtime.capabilities import (
            DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY,
        )

        descriptor = DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY.resolve(str(binding["kind"]))
        container = replace(
            container,
            resources=ContainerResourceIntent.from_runtime(
                resources,
                {kind: descriptor.capability_for(kind) for kind in resources.entries},
            ),
        )
        policy = cast(Mapping[str, object] | None, runtime.get("resource_policy"))
        selection = cast(
            Mapping[str, Sequence[str]] | None, runtime.get("resource_selection")
        )
    if binding["kind"] == "docker":
        from loom.pipeline.executors.docker.commands import build_docker_run_command

        options = {**cast(Mapping[str, object], binding["options"]), "remove": False}
        return build_docker_run_command(
            container_options=container,
            worker_command=worker,
            docker_options=options,
            resource_policy=policy,
            resource_selection=selection,
        )
    from loom.pipeline.executors.apptainer.commands import build_apptainer_exec_command
    from loom.pipeline.executors.apptainer._timeout import namespace_argv

    command = build_apptainer_exec_command(
        container_options=container,
        worker_command=worker,
        apptainer_options=cast(Mapping[str, object], binding["options"]),
        host_environment=environment,
        resource_policy=policy,
        resource_selection=selection,
    )
    return replace(
        command,
        argv=namespace_argv(command.argv),
        redacted_argv=namespace_argv(cast(Sequence[str], command.redacted_argv)),
    )
