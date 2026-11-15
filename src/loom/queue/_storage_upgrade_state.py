"""Startup interlock for explicit stopped storage upgrades.

The operation owns its immutable snapshots and per-owner activation receipts.
Ordinary service startup never performs a conversion or repairs this record.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat

from loom.pipeline.stores.atomic import AtomicWriteError, atomic_write_bytes

from .errors import QueueServiceError


GUARD_NAME = "storage-upgrade.json"


def read_private_json(path: Path) -> dict:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise QueueServiceError(f"storage upgrade file is not private: {path}")
    if info.st_size > 8 * 1024 * 1024:
        raise QueueServiceError("storage upgrade record is too large")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise QueueServiceError("storage upgrade record must be an object")
    return value


def publish_json(path: Path, value: dict) -> None:
    atomic_write_bytes(
        path, json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(),
        durability="strict",
    )
    path.chmod(0o600)


def owner_key(root: Path) -> str:
    return hashlib.sha256(str(root.resolve()).encode()).hexdigest()


def require_storage_upgrade_ready(root: Path, *, entering: bool = False) -> None:
    """Refuse incomplete conversion; under ownership, retain first target entry.

    Call before mutable startup and again under the existing owner/service lock.
    Marking entry is conservative: even a later startup failure disallows old
    snapshot restore. An unselected deployment has no guard and no new effects.
    """
    root = Path(root).resolve()
    path = root / GUARD_NAME
    if not path.exists() and not path.is_symlink():
        return
    try:
        guard = read_private_json(path)
        if set(guard) != {"version", "operation_id", "manifest", "root_id"} or guard["version"] != 1:
            raise ValueError("unsupported guard")
        manifest_path = Path(guard["manifest"])
        if not manifest_path.is_absolute():
            raise ValueError("relative manifest")
        manifest = read_private_json(manifest_path)
        owners = manifest["owners"]
        owner = next(item for item in owners if item["root"] == str(root))
        if (manifest["version"] != 1 or manifest["operation_id"] != guard["operation_id"]
                or owner["root_id"] != guard["root_id"]):
            raise ValueError("guard binding changed")
        if manifest["state"] not in {"ready", "restored"}:
            raise QueueServiceError("storage upgrade is incomplete; resume or restore the retained operation")
        if entering and manifest["state"] == "ready":
            receipt = manifest_path.parent / ("entered-" + owner_key(root) + ".json")
            expected = {"version": 1, "operation_id": guard["operation_id"], "root_id": owner["root_id"]}
            if receipt.exists():
                if read_private_json(receipt) != expected:
                    raise ValueError("activation receipt changed")
            # Re-publish an identical receipt to retry an uncertain directory fsync.
            publish_json(receipt, expected)
    except (OSError, ValueError, KeyError, TypeError, StopIteration, AtomicWriteError) as exc:
        raise QueueServiceError("storage upgrade evidence is unavailable") from exc
