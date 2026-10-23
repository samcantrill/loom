"""Publish a qualified runtime selection through its existing Fleet operation."""

import hashlib
import json
import os
from pathlib import Path

import yaml

from loom.fleet._host import atomic, read
from loom.fleet.configuration import protected_directory
from loom.queue.errors import QueueConflictError


def bind(inventory, target, expected_hash):
    """Capture the exact inventory replacement before native maintenance begins."""
    before = inventory.path.read_bytes()
    if hashlib.sha256(before).hexdigest() != expected_hash:
        raise QueueConflictError("Fleet inventory changed while retaining upgrade intent")
    after = yaml.safe_load(before)
    after["runtime_release"] = str(target)
    encoded = json.dumps(after, sort_keys=True).encode()
    return {
        "path": str(inventory.path),
        "before_sha256": expected_hash,
        "after": after,
        "after_sha256": hashlib.sha256(encoded).hexdigest(),
        "mode": inventory.path.stat().st_mode & 0o777,
    }


def reconcile(operation):
    """Accept only this operation's dispatched inventory publication after a crash."""
    selection = operation.intent.get("inventory_publication")
    if selection is None:
        return
    current = hashlib.sha256(Path(selection["path"]).read_bytes()).hexdigest()
    if current == selection["before_sha256"]:
        return
    dispatched = operation.receipts / "publish-inventory" / "intent.json"
    if (
        current != selection["after_sha256"]
        or not dispatched.exists()
        or read(dispatched) != selection
    ):
        raise QueueConflictError("Fleet inventory changed independently of runtime publication")
    accepted = operation.directory / "accepted-inputs.json"
    updates = read(accepted) if accepted.exists() else {}
    if updates.get(selection["path"]) != current:
        atomic(accepted, {**updates, selection["path"]: current})


def publish(operation):
    """Commit the qualified inventory before reopening admission; resume exact bytes."""
    selection = operation.intent.get("inventory_publication")
    if selection is None:
        # Historical retained operations have no authorized inventory replacement.
        return
    destination = Path(selection["path"])
    directory = operation.receipts / "publish-inventory"
    current = hashlib.sha256(destination.read_bytes()).hexdigest()
    if current != selection["before_sha256"]:
        reconcile(operation)
    else:
        operation.gate()
        operation.recheck()
        protected_directory(directory)
        dispatched = directory / "intent.json"
        if dispatched.exists():
            if read(dispatched) != selection:
                raise QueueConflictError("retained inventory publication intent changed")
        else:
            atomic(dispatched, selection)
        # The operation lock owns one same-filesystem staging path. A process
        # death before replace leaves at most this file, rewritten on resume.
        identity = hashlib.sha256(str(operation.directory).encode()).hexdigest()
        temporary = destination.parent / f".fleet-inventory-{identity}.tmp"
        descriptor = os.open(
            temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW,
            selection["mode"],
        )
        try:
            os.fchmod(descriptor, selection["mode"])
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(json.dumps(selection["after"], sort_keys=True).encode())
                stream.flush()
                os.fsync(stream.fileno())
            if hashlib.sha256(destination.read_bytes()).hexdigest() != selection["before_sha256"]:
                raise QueueConflictError("Fleet inventory changed during runtime publication")
            os.replace(temporary, destination)
            parent = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
        finally:
            temporary.unlink(missing_ok=True)
        reconcile(operation)
    operation.recheck()
    protected_directory(directory)
    atomic(directory / "receipt.json", {"sha256": selection["after_sha256"], "state": "published"})
