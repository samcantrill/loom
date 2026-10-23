"""Assignment-owned storage behind existing container mount targets."""

from __future__ import annotations

import errno
import hashlib
import os
import shutil
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, cast

from loom.serialization import PlainData

if TYPE_CHECKING:
    from ._agent_process_supervisor import ResidentWorkerLaunchProfile


def temporary_mount_targets(
    value: object, container: Mapping[str, PlainData] | None
) -> tuple[str, ...]:
    """Validate the private profile declaration without inspecting storage."""
    from loom.pipeline.executors.containers import (
        ContainerMount,
        parse_container_options,
    )

    if isinstance(value, str) or not isinstance(value, (tuple, list)):
        raise ValueError(
            "temporary_mounts must be a sequence of container mount targets"
        )
    targets = tuple(value)
    if not targets:
        return ()
    if container is None:
        raise ValueError("temporary mounts require a container binding")
    mounts = cast(
        tuple[ContainerMount, ...],
        parse_container_options(container["container"]).mounts,
    )
    return _temporary_targets_for_mounts(targets, mounts)


def _temporary_targets_for_mounts(value: object, mounts: object) -> tuple[str, ...]:
    """Share mount validation with policies whose image is selected at submission."""
    from loom.pipeline.executors.containers import ContainerMount, ContainerMountMode

    if not isinstance(value, (list, tuple)):
        raise ValueError(
            "temporary_mounts must be a sequence of container mount targets"
        )
    targets = tuple(value)
    if any(
        not isinstance(item, str) or not Path(item).is_absolute() for item in targets
    ):
        raise ValueError("temporary mount targets must be absolute paths")
    if len(set(targets)) != len(targets):
        raise ValueError("temporary mount targets must be unique")
    mounts = cast(tuple[ContainerMount, ...], mounts)
    by_target = {mount.target: mount for mount in mounts}
    for target in targets:
        mount = by_target.get(target)
        if mount is None or mount.mode is not ContainerMountMode.READ_WRITE:
            raise ValueError("temporary mount must select an existing writable mount")
        if target == "/" or str(Path(target)) != target or ".." in Path(target).parts:
            raise ValueError("temporary mount target must be canonical and below root")
        for other in mounts:
            if other is mount:
                continue
            if _overlap(Path(target), Path(other.target)) or _overlap(
                Path(mount.source), Path(other.source)
            ):
                raise ValueError(
                    "temporary mount must not overlap another installed mount"
                )
    return targets


def _overlap(left: Path, right: Path) -> bool:
    return left.is_relative_to(right) or right.is_relative_to(left)


def assignment_mounts(
    profile: ResidentWorkerLaunchProfile, *, workspace: Path, agent_id: str
) -> dict[str, Path]:
    """Project exact host paths from the journaled profile and assignment identity."""
    from loom.pipeline.executors.containers import (
        ContainerMount,
        parse_container_options,
    )

    if not profile.temporary_mounts:
        return {}
    assert profile.container is not None
    mounts = cast(
        tuple[ContainerMount, ...],
        parse_container_options(profile.container["container"]).mounts,
    )
    scope = hashlib.sha256(
        (agent_id + "\0" + os.path.abspath(workspace)).encode("utf-8")
    ).hexdigest()
    selected = {}
    for mount in mounts:
        if mount.target in profile.temporary_mounts:
            base = Path(mount.source)
            if not base.is_absolute() or ".." in base.parts:
                raise ValueError(
                    "temporary mount source must be an absolute canonical path"
                )
            if _overlap(base, workspace) or _overlap(base, profile.project_root):
                raise ValueError(
                    "temporary storage must not overlap execution or project evidence"
                )
            selected[mount.target] = base / "attempts" / scope
    return selected


def _directory(path: Path, *, create: bool = False) -> None:
    if create:
        path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise OSError(
            errno.ENOTDIR,
            "temporary storage must be a non-symlink directory",
            str(path),
        )
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PermissionError(
            errno.EACCES,
            "temporary storage requires an owner-private directory",
            str(path),
        )


def prepare_assignment_storage(
    profile: ResidentWorkerLaunchProfile, *, workspace: Path, agent_id: str
) -> None:
    """Allocate beneath the declared host base after recording launch ownership."""
    for path in assignment_mounts(
        profile, workspace=workspace, agent_id=agent_id
    ).values():
        _directory(path.parent.parent, create=True)
        _directory(path.parent, create=True)
        _directory(path, create=True)


def cleanup_assignment_storage(
    profile: ResidentWorkerLaunchProfile, *, workspace: Path, agent_id: str
) -> None:
    """Remove exact owned directories; caller must first prove containment.

    Idempotence covers a crash after deletion but before journal acknowledgement.
    Missing roots need no repair. Other storage errors remain failures for retry.
    The mount base, sibling attempts and retained workspaces are never removed.
    """
    for path in assignment_mounts(
        profile, workspace=workspace, agent_id=agent_id
    ).values():
        try:
            _directory(path.parent.parent)
            _directory(path.parent)
            _directory(path)
        except FileNotFoundError:
            continue
        shutil.rmtree(path)
