"""Bind physical Apptainer launches to a private, verified regular image file."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import Future
from contextlib import contextmanager
from dataclasses import dataclass, replace
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from typing import cast

from loom.pipeline.executors.apptainer.commands import ApptainerExecCommand
from loom.serialization import PlainData
from ._phase_timing import phase
from .submitted_execution import SubmittedImage, _opened_image


@dataclass
class _Materialization:
    ready: Future
    owners: int = 1


_lock = Lock()
_active: dict[tuple, _Materialization] = {}


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
def image_for_launch(image: SubmittedImage, roots: Mapping[str, PlainData], operation_id: str):
    """Keep one launcher-owned image alive until the runtime finishes using it.

    A published pathname can change after checking. Singularity canonicalizes
    procfs descriptor links, so it must receive a stable, private filename.
    Concurrent launches can share the copy only for the same pinned snapshot.
    """
    from ._immutable_tree import _snapshot

    alias = str(image.location["root_id"])
    root = cast(Mapping[str, PlainData], roots[alias])
    with _opened_image(image, roots) as (path, source):
        info = os.fstat(source.fileno())
        mount = _snapshot(source.fileno())
        key = None if mount is None else (alias, str(path), mount, info.st_dev, info.st_ino,
                                          image.sha256, image.size_bytes, json.dumps(dict(root), sort_keys=True, default=dict))
        with _lock:
            entry = None if key is None else _active.get(key)
            owner = entry is None
            if entry is None:
                entry = _Materialization(Future())
                if key is not None:
                    _active[key] = entry
            else:
                entry.owners += 1
        try:
            with phase("submitted_image_verification", operation_id=operation_id) as facts:
                facts.update(size_bytes=image.size_bytes, shared_verification=not owner)
                if owner:
                    directory = None
                    try:
                        directory = TemporaryDirectory(prefix="loom-submitted-image-")
                        private = Path(directory.name) / "image.sif"
                        _copy_verified(source, image, private)
                        entry.ready.set_result((directory, private))
                    except BaseException as exc:
                        if directory is not None:
                            directory.cleanup()
                        entry.ready.set_exception(exc)
                        raise
                _, private = entry.ready.result()
            yield path, private
        finally:
            with _lock:
                entry.owners -= 1
                last = entry.owners == 0
                if last and key is not None:
                    del _active[key]
            if last and entry.ready.done() and entry.ready.exception() is None:
                entry.ready.result()[0].cleanup()


def physical_command(command: ApptainerExecCommand, image_paths) -> ApptainerExecCommand:
    """Substitute only the projected image operand in the physical command."""
    original, verified = image_paths
    worker = cast(Sequence[str], command.metadata["worker_command"])
    index = len(command.argv) - len(worker) - 1
    if index < 2 or command.argv[index] != str(original) or tuple(command.argv[index + 1:]) != tuple(worker):
        raise ValueError("projected command does not select the verified submitted image")
    return replace(command, argv=(*command.argv[:index], str(verified), *command.argv[index + 1:]))
