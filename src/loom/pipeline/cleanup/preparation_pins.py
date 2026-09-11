"""Filesystem retention for evidence owned by a durable preparation operation.

Pins live beside the retained directory, so adding a pin never rewrites a
complete prepared run. There is deliberately no unpin or expiration operation.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat

from loom.pipeline.stores.atomic import atomic_write_bytes
from loom.serialization import stable_json_bytes

from .errors import CleanupSafetyError


_PIN_DIRECTORY = ".loom-preparation-pins"


def retain_preparation_path(
    path: Path, *, coordinator_id: str, operation_id: str
) -> None:
    """Pin one capture or run directory without writing inside that directory."""
    target = path.absolute()
    namespace = target.parent / _PIN_DIRECTORY
    directory = namespace / hashlib.sha256(target.name.encode()).hexdigest()
    for item in (namespace, directory):
        item.mkdir(mode=0o700, parents=True, exist_ok=True)
        if item.is_symlink() or not item.is_dir():
            raise CleanupSafetyError("preparation retention directory is invalid")
    identity = hashlib.sha256(
        (coordinator_id + "\0" + operation_id).encode()
    ).hexdigest()
    pin = directory / f"{identity}.json"
    encoded = stable_json_bytes(
        {
            "schema_version": 1,
            "coordinator_id": coordinator_id,
            "operation_id": operation_id,
            "name": target.name,
        }
    )
    try:
        metadata = pin.lstat()
    except FileNotFoundError:
        atomic_write_bytes(pin, encoded)
        pin.chmod(0o600)
    else:
        if not stat.S_ISREG(metadata.st_mode) or pin.read_bytes() != encoded:
            raise CleanupSafetyError("preparation retention identity conflicts")
    for item in (pin, directory, namespace, target.parent):
        descriptor = os.open(item, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def preparation_path_is_retained(path: Path) -> bool:
    """Refuse a pinned path, its descendants, or deletion of its retained pins."""
    target = path.absolute()
    if _PIN_DIRECTORY in target.parts:
        return True
    try:
        for ancestor in (target, *target.parents):
            directory = (
                ancestor.parent
                / _PIN_DIRECTORY
                / hashlib.sha256(ancestor.name.encode()).hexdigest()
            )
            if directory.exists() or directory.is_symlink():
                return True
        # Deleting an ancestor must not bypass descendant pins. Ordinary
        # per-run cleanup returns above; this handles explicit wider targets.
        return target.is_dir() and next(target.rglob(_PIN_DIRECTORY), None) is not None
    except OSError:
        # An unreadable protected retention directory is not proof of release.
        return True
