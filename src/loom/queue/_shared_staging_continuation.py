"""Continue incomplete shared-output staging after native provider release.

This is a native storage operation, not scientific recovery admission. Its caller
must own the current assignment and supply its live-authority check. The selected
predecessor must occur in the coordinator-admitted recovery delivery, whose
construction requires positive release and retained recovery evidence.

Only an unsealed output staging tree moves. Retained recovery trees and accepted
publications are never changed. A durable intent precedes rename, allowing both
the same assignment and a later released successor to finish an interrupted
handoff. Payload inodes survive; applications still admit their assembly identity
and verify received resources before using them.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from loom.pipeline.stores.atomic import atomic_write_bytes
from loom.pipeline.stores.errors import ArtifactStoreError, AtomicWriteError
from loom.pipeline.stores.shared_artifacts import RECEIPT, contained, encoded, receipt_bytes
from loom.serialization import PlainData

from . import _shared_recovery as recovery
from ._shared_publication import identity, publication_id, selected, staging_tree
from .errors import QueueConflictError

if TYPE_CHECKING:
    from ._shared_publication import PublicationRequest


_OWNERSHIP_LIMIT = 64 * 1024
_INTENTS = ".loom-staging-continuations"


def _stage_path(root: Path, owner: Mapping[str, Any]) -> Path:
    machine = hashlib.sha256(owner["agent_id"].encode()).hexdigest()
    relative = (
        f"loom-work/{machine}/{owner['assignment_id']}/{owner['attempt_id']}"
        f"/artifacts/{owner['stage_name']}"
    )
    return contained(root, relative, exists=False)


def _intent_path(root: Path, tree: Path, owner: Mapping[str, Any]) -> Path:
    # Intents travel with the payload, so another interrupted handoff does not
    # depend on an abandoned parent's unpinned working directory.
    path = tree / _INTENTS / f"{publication_id(owner)}.json"
    return contained(root, path.relative_to(root).as_posix(), exists=False)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(receipt_bytes(contained(path.parent, path.name), _OWNERSHIP_LIMIT))
    if not isinstance(value, dict):
        raise QueueConflictError("staging continuation ownership is not a mapping")
    return value


def _publication_owner(reference: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in reference["identity"].items() if key != "origin_run_id"}


def _admit_predecessor(reference: object, predecessors: list[Any]) -> dict[str, Any]:
    admitted = recovery._reference(reference)
    if admitted not in predecessors:
        raise QueueConflictError("staging continuation predecessor is not authorized")
    return admitted


def _require_unpublished(root: Path, owner: Mapping[str, Any]) -> None:
    final = contained(root, f"loom-artifacts/{publication_id(owner)}", exists=False)
    if final.exists():
        raise QueueConflictError("accepted publication requires native settlement, not staging continuation")


def _admit_source_marker(
    root: Path,
    tree: Path,
    marker: Mapping[str, Any],
    reference: dict[str, Any],
    predecessors: list[Any],
) -> None:
    """Resolve an interrupted earlier handoff without writing any old journal."""
    if set(marker) != {"schema_version", "identity"} or marker["schema_version"] != 1:
        raise QueueConflictError("sealed or unknown staging requires native settlement")
    visited = set()
    while True:
        owner = _publication_owner(reference)
        _require_unpublished(root, owner)
        if marker == {"schema_version": 1, "identity": owner}:
            return
        key = reference["publication_id"]
        if key in visited:
            raise QueueConflictError("staging continuation ownership cycle")
        visited.add(key)
        intent = _read(_intent_path(root, tree, owner))
        if set(intent) != {"schema_version", "source", "destination"} or (
            intent["schema_version"] != 1 or intent["destination"] != owner
        ):
            raise QueueConflictError("staging continuation source ownership conflicts")
        previous = _admit_predecessor(intent["source"], predecessors)
        if previous["identity"]["attempt"] >= reference["identity"]["attempt"]:
            raise QueueConflictError("staging continuation source order conflicts")
        previous_tree = _stage_path(root, _publication_owner(previous))
        if previous_tree.exists():
            raise QueueConflictError("staging continuation has two source trees")
        reference = previous


def _sync_ancestry(directory: Path, root: Path) -> None:
    from ._remote_stage_execution import _fsync_directory

    while True:
        _fsync_directory(directory)
        if directory == root:
            return
        directory = directory.parent


def continue_staging(
    request: PublicationRequest,
    roots: Mapping[str, PlainData],
    *,
    predecessor: Mapping[str, Any],
    agent_id: str,
    fence: str,
    require_live_owner: Callable[[], Mapping[str, PlainData]],
) -> Path:
    """Move one authorized, unsealed predecessor staging tree without copying.

    Call under native assignment serialization, before exposing the destination
    to a worker. ``require_live_owner`` must recheck current native authority and
    return its publication owner (assignment, attempt, stage, agent and fence),
    which must equal the requested destination owner on every mutation. A timeout
    alone never authorizes the predecessor. This operation does not grant or
    transfer the assignment itself.

    A failure can leave a durable intent, a renamed tree with its previous owner
    marker, or a current marker whose parent sync is uncertain. Stop the caller
    after any failure. Replaying the same operation repairs those boundaries;
    a later admitted attempt can continue the renamed tree as well. An initialized
    empty destination is allowed, but existing application outputs are never
    overwritten. Accepted or sealed output trees require native settlement.

    All locations use one admitted writable shared root, so rename either keeps
    payload inodes or fails; there is deliberately no copy fallback. The returned
    path is private runtime information, not durable artifact identity.
    """
    owner = identity(request, agent_id=agent_id, fence=fence)

    def require_owner() -> None:
        if require_live_owner() != owner:
            raise QueueConflictError("staging continuation current ownership conflicts")

    try:
        require_owner()
        wire = recovery.validate_wire(request)
        selection = selected(request)
        if wire is None or selection is None:
            raise QueueConflictError("staging continuation requires native recovery delivery")
        recovery.current_tree(request, roots, agent_id=agent_id)
        reference = _admit_predecessor(predecessor, wire["predecessors"])
        # Inspect the native immutable receipt; application admission owns the
        # mutable staging payload and must verify its resource receipts later.
        recovery.inspect(reference, roots)
        root_binding = cast(Mapping[str, PlainData], roots[selection[0]])
        root = Path(str(root_binding["host_path"]))
        source_owner = _publication_owner(reference)
        source = _stage_path(root, source_owner)
        destination = staging_tree(request, roots, agent_id)
        _require_unpublished(root, owner)
        _require_unpublished(root, source_owner)
        intent_path = _intent_path(root, source if source.exists() else destination, owner)
        intent = {"schema_version": 1, "source": reference, "destination": owner}
        recorded = intent_path.exists()
        if recorded and _read(intent_path) != intent:
            raise QueueConflictError("staging continuation replay conflicts")

        if source.exists():
            _admit_source_marker(root, source, _read(source / RECEIPT), reference, wire["predecessors"])
            if destination.exists():
                children = tuple(destination.iterdir())
                if children and (
                    children != (destination / RECEIPT,)
                    or _read(destination / RECEIPT) != {"schema_version": 1, "identity": owner}
                ):
                    raise QueueConflictError("staging continuation destination contains output")
                if not children and not recorded:
                    raise QueueConflictError("staging continuation destination has no owner")
            if not recorded:
                require_owner()
                atomic_write_bytes(intent_path, encoded(intent), durability="strict")
            # Persist the journal's directory links before moving its tree.
            # Repeating the ancestry barriers repairs an uncertain earlier mkdir.
            require_owner()
            _sync_ancestry(intent_path.parent, root)
            if not destination.parent.exists():
                require_owner()
                atomic_write_bytes(
                    destination / RECEIPT,
                    encoded({"schema_version": 1, "identity": owner}),
                    durability="strict",
                )
            require_owner()
            _sync_ancestry(destination.parent, root)
            if destination.exists():
                # Only the verified empty initializer may be removed. The
                # recorded intent makes a crash between these operations replayable.
                require_owner()
                (destination / RECEIPT).unlink(missing_ok=True)
                require_owner()
                destination.rmdir()
            require_owner()
            os.rename(source, destination)
        elif not recorded or not destination.exists():
            raise QueueConflictError("staging continuation source is unavailable")

        marker = _read(destination / RECEIPT)
        desired = {"schema_version": 1, "identity": owner}
        if marker != desired:
            _admit_source_marker(root, destination, marker, reference, wire["predecessors"])
            require_owner()
            atomic_write_bytes(destination / RECEIPT, encoded(desired), durability="strict")
        # Repeat barriers on replay even if rename/marker replacement was already
        # visible. The intent is not an acknowledgement of their durability.
        require_owner()
        _sync_ancestry(destination / _INTENTS, root)
        _sync_ancestry(source.parent, root)
        return destination
    except (ArtifactStoreError, AtomicWriteError, OSError, ValueError) as exc:
        raise QueueConflictError(str(exc)) from exc
