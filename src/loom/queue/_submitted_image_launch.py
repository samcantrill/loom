"""Bind physical Apptainer launches to a private, verified regular image file."""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field, replace
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from typing import TYPE_CHECKING, cast

from loom.pipeline.executors.apptainer.commands import ApptainerExecCommand
from loom.serialization import PlainData
from ._phase_timing import phase
from .submitted_execution import SubmittedImage, _opened_image

if TYPE_CHECKING:
    from ._agent_process_supervisor import SupervisorLaunchConfiguration


@dataclass
class _Materialization:
    reserved_bytes: int
    ready: Future[Path] = field(default_factory=Future)
    resources: ExitStack = field(default_factory=ExitStack)
    owners: int = 1


class VerifiedImageCache:
    """Process-owned verified copies, with active launches pinning their entries."""

    def __init__(self, directory: Path | None, *, max_bytes: int = 8 * 1024**3) -> None:
        self.directory = directory
        self.max_bytes = max_bytes if directory is not None else 0
        self._entries: OrderedDict[tuple, _Materialization] = OrderedDict()
        self._reserved = 0
        self._lock = Lock()

    @classmethod
    def for_supervisor(cls, root: Path, configuration: SupervisorLaunchConfiguration) -> VerifiedImageCache:
        # The protected service directory must stay outside guest-writable mount trees.
        if not configuration.container_policies:
            return cls(None)
        from loom.pipeline.executors.containers import ContainerMount, parse_container_options
        mounts = [m for policy in configuration.container_policies for m in policy.mounts]
        bindings = [policy.shared_roots for policy in configuration.container_policies]
        for profile in configuration.profiles:
            if profile.container is not None:
                if not profile.shared_roots:
                    # The installed profile exposes the entire agent directory.
                    return cls(None)
                parsed = parse_container_options(profile.container["container"])
                mounts.extend(cast(Sequence[ContainerMount], parsed.mounts))
                bindings.append(profile.shared_roots)
        writable = [m.source for m in mounts if m.mode == "rw"]
        for roots in bindings:
            for raw in roots.values():
                binding = cast(Mapping[str, PlainData], raw)
                if binding["access"] == "rw" and binding["container_path"] is not None:
                    writable.append(str(binding["host_path"]))
        if any(root.is_relative_to(Path(source).resolve()) for source in writable):
            return cls(None)
        return cls(root)

    def recover_scratch(self, directory: Path, quiescent: Callable[[], bool]) -> None:
        """Called under the service lock, before accepting new launches."""
        old = list(directory.glob("loom-submitted-image-*"))
        if not old:
            return
        if not quiescent():
            # The preceding runtime might still need its pathname. Use ordinary
            # launch scratch until a quiescent service can reclaim this budget.
            self.max_bytes = 0
            return
        for scratch in old:
            (scratch / "image.sif").unlink(missing_ok=True)
            scratch.rmdir()

    def acquire(self, key: tuple, size: int) -> tuple[_Materialization, bool]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                self._entries.move_to_end(key)
                entry.owners += 1
                return entry, False
            reserved = 0
            if size <= self.max_bytes:
                # Also bound the source descriptors pinned by tiny warm images.
                retained = [item for item in self._entries.items() if item[1].reserved_bytes]
                idle = [(k, e) for k, e in retained if not e.owners]
                active_size = self._reserved - sum(e.reserved_bytes for _, e in idle)
                if active_size + size <= self.max_bytes and len(retained) - len(idle) < 8:
                    count = len(retained)
                    for old_key, old in idle:
                        if self._reserved + size <= self.max_bytes and count < 8:
                            break
                        self._remove(old_key, old)
                        count -= 1
                    reserved = size
                    self._reserved += size
            entry = _Materialization(reserved)
            self._entries[key] = entry
            return entry, True

    def release(self, key: tuple, entry: _Materialization) -> None:
        with self._lock:
            entry.owners -= 1
            if not entry.owners and not entry.reserved_bytes and self._entries.get(key) is entry:
                self._remove(key, entry)

    def discard_failed(self, key: tuple, entry: _Materialization) -> None:
        with self._lock:
            self._remove(key, entry)

    def clear_idle(self) -> None:
        with self._lock:
            for key, entry in list(self._entries.items()):
                if not entry.owners:
                    self._remove(key, entry)

    def _remove(self, key: tuple, entry: _Materialization) -> None:
        entry.resources.close()
        self._reserved -= entry.reserved_bytes
        del self._entries[key]


# Standalone probes and Slurm share overlapping users only.
_active_images = VerifiedImageCache(None)


def _copy_verified(source, image, private):
    with private.open("xb+") as copied:
        # FICLONE creates a separate copy-on-write inode on supporting storage.
        try:
            fcntl.ioctl(copied.fileno(), 0x40049409, source.fileno())
        except OSError as exc:
            if exc.errno not in {errno.EXDEV, errno.EINVAL, errno.EOPNOTSUPP, errno.ENOTTY, errno.ENOSYS}:
                raise
            digest = hashlib.sha256()
            remaining = image.size_bytes
            while remaining:
                data = source.read(min(1024 * 1024, remaining))
                if not data:
                    break
                copied.write(data)
                digest.update(data)
                remaining -= len(data)
            if remaining or source.read(1):
                raise ValueError("submitted image bytes differ from retained size")
        else:
            digest = hashlib.file_digest(copied, "sha256")
        if digest.hexdigest() != image.sha256:
            raise ValueError("submitted image bytes differ from retained intent")
        os.fchmod(copied.fileno(), 0o400)


@contextmanager
def image_for_launch(image: SubmittedImage, roots: Mapping[str, PlainData], operation_id: str,
                     *, cache: VerifiedImageCache = _active_images):
    """Keep the verified image pinned until the physical runtime releases it.

    Every launch reopens the authorized source. Only a read-only kernel
    SquashFS inode can share verification, including between sequential uses
    when a supervisor has reserved space for it.
    """
    from ._immutable_tree import _snapshot

    with ExitStack() as lease:
        with phase("submitted_image_verification", operation_id=operation_id) as facts:
            facts.update(size_bytes=image.size_bytes, shared_verification=False)
            path, source = lease.enter_context(_opened_image(image, roots))
            mount = _snapshot(source.fileno())
            if mount is None:
                key = None
                entry, owner = _Materialization(0), True
                lease.callback(entry.resources.close)
            else:
                alias = str(image.location["root_id"])
                root = cast(Mapping[str, PlainData], roots[alias])
                info = os.fstat(source.fileno())
                key = (mount, info.st_dev, info.st_ino, alias, json.dumps(dict(root), sort_keys=True, default=dict),
                       image.sha256, image.size_bytes)
                entry, owner = cache.acquire(key, image.size_bytes)
                lease.callback(cache.release, key, entry)
            facts.update(shared_verification=not owner)
            if owner:
                try:
                    if entry.reserved_bytes:
                        # Keep the mount ID and inode from being recycled between launches.
                        entry.resources.enter_context(os.fdopen(os.dup(source.fileno()), "rb"))
                    directory = entry.resources.enter_context(TemporaryDirectory(
                        prefix="loom-submitted-image-", dir=cache.directory if entry.reserved_bytes else None,
                    ))
                    private = Path(directory) / "image.sif"
                    _copy_verified(source, image, private)
                    entry.ready.set_result(private)
                except BaseException as exc:
                    entry.ready.set_exception(exc)
                    if key is not None:
                        cache.discard_failed(key, entry)
                    raise
            private = entry.ready.result()
        yield path, private


def physical_command(command: ApptainerExecCommand, image_paths) -> ApptainerExecCommand:
    """Substitute only the projected image operand in the physical command."""
    original, verified = image_paths
    worker = cast(Sequence[str], command.metadata["worker_command"])
    index = len(command.argv) - len(worker) - 1
    if index < 2 or command.argv[index] != str(original) or tuple(command.argv[index + 1:]) != tuple(worker):
        raise ValueError("projected command does not select the verified submitted image")
    return replace(command, argv=(*command.argv[:index], str(verified), *command.argv[index + 1:]))
