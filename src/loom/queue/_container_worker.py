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


def _base_worker_mounts(profile: ResidentWorkerLaunchProfile, workspace: Path, *,
                        runtime: Mapping[str, PlainData] | None = None,
                        shared_scope: Mapping[str, PlainData] | None = None):
    """The effective installed and required mounts before shared per-stage IO."""
    from loom.pipeline.executors.containers import ContainerMount, ContainerMountMode, parse_container_options

    assert profile.container is not None
    container = parse_container_options(profile.container["container"])
    required = {
        **({str(profile.project_root): "ro"} if not profile.shared_roots else {}),
        str(workspace if profile.shared_roots else workspace.parent.parent): "rw",
        **{
            str(path): "ro"
            for path in profile.preparation_shared_roots.values()
            if shared_scope is None and (runtime is not None or path.exists())
        },
    }
    mounts = {
        mount.target: mount
        for mount in cast(tuple[ContainerMount, ...], container.mounts)
    }
    if profile.shared_roots:
        for mount in mounts.values():
            for raw in profile.shared_roots.values():
                host = Path(str(cast(Mapping[str, PlainData], raw)["host_path"]))
                source = Path(mount.source)
                if source.is_relative_to(host) or host.is_relative_to(source):
                    raise ValueError("shared roots must be mounted through per-stage selection")
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
    return mounts


def build_container_worker(
    profile: ResidentWorkerLaunchProfile,
    *,
    workspace: Path,
    worker: Sequence[str],
    environment: Mapping[str, str],
    runtime: Mapping[str, PlainData] | None = None,
    shared_scope: Mapping[str, PlainData] | None = None,
    shared_snapshot: object = None,
    agent_id: str | None = None,
):
    """Reuse container resource projection with assignment-owned path parity."""
    from loom.pipeline.executors.containers import (
        ContainerEnvironment,
        ContainerMount,
        ContainerResourceIntent,
        parse_container_options,
    )

    binding = profile.container
    assert binding is not None
    container = parse_container_options(binding["container"])
    mounts = _base_worker_mounts(profile, workspace, runtime=runtime, shared_scope=shared_scope)
    if shared_scope is not None:
        from .shared_execution import require_bindings, resolve
        require_bindings(shared_scope, profile.shared_roots)
        for item in cast(Sequence[Mapping[str, PlainData]], shared_scope["locations"]):
            root = cast(Mapping[str, PlainData], profile.shared_roots[str(item["root_id"])])
            if root["container_path"] is None:
                raise ValueError("shared container target is missing")
            source = str(resolve(root, str(item["path"])))
            target = str(Path(str(root["container_path"])) / str(item["path"]))
            mounts[target] = ContainerMount(source=source, target=target, mode="ro")
        # Root challenge files permit the child to recheck its actual namespace.
        for alias in cast(Mapping[str, PlainData], shared_scope["roots"]):
            root = cast(Mapping[str, PlainData], profile.shared_roots[alias])
            challenge = cast(Mapping[str, PlainData], root["challenge"])
            target = str(Path(str(root["container_path"])) / str(challenge["path"]))
            mounts[target] = ContainerMount(source=str(resolve(root, str(challenge["path"]))), target=target, mode="ro")
        from ._remote_stage_execution import _ResidentAssignmentWorkspace
        from ._shared_publication import selected, staging_tree, resolve_input
        from loom.pipeline.stores.shared_artifacts import binding as shared_binding
        assignment = _ResidentAssignmentWorkspace(workspace.parent.parent, workspace.name).request()
        selection = selected(assignment)
        if selection is not None:
            if agent_id is None:
                raise ValueError("shared output mount requires the assignment machine identity")
            alias, _ = selection
            root = cast(Mapping[str, PlainData], profile.shared_roots[alias])
            source = staging_tree(assignment, profile.shared_roots, agent_id, create=True)
            target = Path(str(root["container_path"])) / source.relative_to(str(root["host_path"]))
            mounts[str(target)] = ContainerMount(source=str(source), target=str(target), mode="rw")
        from ._shared_recovery import validate_wire, current_tree, resolve as resolve_recovery
        recovery = validate_wire(assignment)
        if recovery is not None:
            root = cast(Mapping[str, PlainData], profile.shared_roots[recovery["root_id"]])
            source = current_tree(assignment, profile.shared_roots)
            source.mkdir(parents=True, exist_ok=True)
            target = Path(str(root["container_path"])) / recovery["tree"]
            mounts[str(target)] = ContainerMount(source=str(source), target=str(target), mode="rw")
            for reference in recovery["predecessors"]:
                source = resolve_recovery(reference, profile.shared_roots)
                target = Path(str(root["container_path"])) / reference["tree"]
                mounts[str(target)] = ContainerMount(source=str(source), target=str(target), mode="ro")
        for item in assignment.inputs:
            reference = shared_binding(item.metadata)
            if reference is None:
                continue
            resolve_input(item, profile.shared_roots)
            root = cast(Mapping[str, PlainData], profile.shared_roots[str(reference["root_id"])])
            source = resolve(root, str(reference["tree"]))
            target = Path(str(root["container_path"])) / str(reference["tree"])
            mounts[str(target)] = ContainerMount(source=str(source), target=str(target), mode="ro")
        if shared_snapshot is not None:
            from .preparation import SharedInputReceipt
            assert isinstance(shared_snapshot, SharedInputReceipt)
            from .shared_execution import snapshot_mount
            source, target = snapshot_mount(profile, shared_snapshot)
            mounts[str(target)] = ContainerMount(source=str(source), target=str(target), mode="ro")
    declared = cast(ContainerEnvironment, container.environment)
    merged = {**declared.variables, **environment}
    if profile.shared_roots:
        merged.pop("PYTHONPATH", None)
        merged["PYTHONSAFEPATH"] = "1"
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
        workdir=str(workspace) if profile.shared_roots else str(profile.project_root),
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
    def namespaced(argv: Sequence[str]) -> tuple[str, ...]:
        if profile.shared_roots:
            # Disable implicit host/home/tmp/cwd and administrator bind exposure;
            # the explicit selected mounts remain the workload's filesystem set.
            argv = (argv[0], "exec", "--contain", "--no-mount", "hostfs,bind-paths,cwd", *argv[2:])
        return namespace_argv(argv)

    return replace(
        command,
        argv=namespaced(command.argv),
        redacted_argv=namespaced(cast(Sequence[str], command.redacted_argv)),
    )
