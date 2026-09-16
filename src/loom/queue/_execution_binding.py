"""Assignment-owned execution identity and protected local state visibility."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from loom.pipeline.stores import run_uri_to_path
from loom.serialization import PlainData

if TYPE_CHECKING:
    from loom.pipeline.execution.models import StageWorkerRequest
    from loom.pipeline.stores import LocalRunStore
    from ._agent_process_supervisor import ResidentWorkerLaunchProfile


def execution_binding(
    request: StageWorkerRequest,
    environment: str,
    *,
    store: LocalRunStore | None = None,
    launch: ResidentWorkerLaunchProfile | None = None,
    workspace: Path | None = None,
) -> dict[str, PlainData]:
    from .managed_local_preparation import _validate_run_name
    from .models import validate_queue_id

    original = (
        run_uri_to_path(request.run_uri)
        if request.run_uri.startswith("file://")
        else None
    )
    run_id = _validate_run_name(
        original.name if original is not None else request.run_uri
    )
    validate_queue_id(request.stage_name, "execution origin node")
    visible = None
    if store is not None and launch is not None:
        root = store.root.resolve()
        if original is None or original.parent != root:
            raise ValueError("execution state root escapes protected run storage")
        visible = str(original)
        if launch.container is not None:
            visible = _container_state_root(original, launch, workspace=workspace)
    return {
        "schema_version": 1,
        "origin_run_id": run_id,
        "origin_node_id": request.stage_name,
        "attempt": request.attempt,
        "environment_fingerprint": environment,
        "run_state_root": visible,
    }


def _container_state_root(
    root: Path, launch: ResidentWorkerLaunchProfile, *, workspace: Path | None = None
) -> str | None:
    from loom.pipeline.executors.containers import (
        ContainerMount,
        ContainerMountMode,
        parse_container_options,
    )

    assert launch.container is not None
    mounts = cast(
        tuple[ContainerMount, ...],
        parse_container_options(launch.container["container"]).mounts,
    )
    effective_mounts = mounts
    if workspace is not None:
        from ._container_worker import _base_worker_mounts

        effective_mounts = tuple(
            _base_worker_mounts(launch, workspace, runtime={}).values()
        )
    # Only explicit installed writable mounts authorize durable state. The
    # worker's implicit workspace/project mounts do not grant run-store access.
    for mount in sorted(
        mounts, key=lambda item: len(Path(item.source).parts), reverse=True
    ):
        source = Path(mount.source).resolve()
        if (
            not root.is_relative_to(source)
            or cast(ContainerMountMode, mount.mode).value != "rw"
        ):
            continue
        target = Path(mount.target) / root.relative_to(source)
        covering = [
            item for item in effective_mounts if target.is_relative_to(item.target)
        ]
        effective = max(covering, key=lambda item: len(Path(item.target).parts))
        if effective != mount:
            continue
        if not launch.shared_roots and target.is_relative_to(launch.project_root):
            # build_container_worker installs this read-only path-parity mount.
            if len(launch.project_root.parts) >= len(Path(mount.target).parts):
                continue
        return str(target)
    return None
