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
WIRE = "loom.output_staging_continuation"
_PRINCIPAL = "native-output-staging"
_GRANT_QUERY = (
    "SELECT digest, result_json FROM agent_receipts WHERE principal_id=? "
    "AND operation='continue_staging' AND idempotency_key=?"
)


def requested(request: PublicationRequest) -> bool:
    from .shared_execution import assignment_scope

    scope = assignment_scope(request.fingerprint)
    return scope is not None and "staging_continuation" in scope


def validate_binding(request: PublicationRequest, recovery_wire: Mapping[str, Any]) -> dict[str, Any] | None:
    """Admit the coordinator-selected source in an immutable native delivery."""
    raw = request.worker_metadata.get(WIRE)
    if not requested(request):
        if raw is not None:
            raise QueueConflictError("output staging continuation was not requested")
        return None
    if not isinstance(raw, Mapping) or set(raw) != {"schema_version", "predecessor"} or (
        type(raw["schema_version"]) is not int or raw["schema_version"] != 1
    ):
        raise QueueConflictError("output staging continuation delivery is missing or invalid")
    if raw["predecessor"] is None:
        return None
    return _admit_predecessor(raw["predecessor"], recovery_wire["predecessors"])


def may_own_unstarted_progress(row: Mapping[str, Any], metadata: Mapping[str, Any]) -> bool:
    """A granted handoff can own assembly before any worker receives a permit."""
    value = metadata.get(WIRE)
    return row["fence"] is not None and isinstance(value, Mapping) and value.get("predecessor") is not None


def _empty_staging(tree: Path) -> bool:
    if not tree.exists():
        return True
    with os.scandir(tree) as entries:
        return all(entry.name == RECEIPT for entry in entries)


def select_predecessor(predecessors: list[Any], roots: Mapping[str, PlainData]) -> dict[str, Any] | None:
    """Find the latest surviving unsealed tree using only authorized locations.

    A grant interrupted before rename leaves the bytes in an earlier attempt;
    an empty newly prepared mount directory is not assembly progress.
    """
    authorized = _predecessor_map(predecessors)
    for reference in reversed(authorized.values()):
        root_binding = cast(Mapping[str, PlainData], roots[reference["root_id"]])
        root = Path(str(root_binding["host_path"]))
        owner = _publication_owner(reference)
        _require_unpublished(root, owner)
        tree = _stage_path(root, owner)
        if not tree.exists():
            continue
        marker = tree / RECEIPT
        if marker.exists():
            _admit_source_marker(root, tree, _read(marker), reference, authorized)
        elif not _empty_staging(tree):
            raise QueueConflictError("uninitialized predecessor staging contains output")
        if not _empty_staging(tree):
            return reference
    return None


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


def _predecessor_map(predecessors: list[Any]) -> dict[str, dict[str, Any]]:
    authorized: dict[str, dict[str, Any]] = {}
    for raw in predecessors:
        reference = recovery._reference(raw)
        key = reference["publication_id"]
        if key in authorized:
            raise QueueConflictError("staging continuation has duplicate predecessor ownership")
        authorized[key] = reference
    return authorized


def _admit_predecessor(reference: object, predecessors: list[Any] | Mapping[str, Any]) -> dict[str, Any]:
    admitted = recovery._reference(reference)
    matches = (
        predecessors.get(admitted["publication_id"]) == admitted
        if isinstance(predecessors, Mapping) else admitted in predecessors
    )
    if not matches:
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
    predecessors: Mapping[str, Any],
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
        if not _empty_staging(previous_tree):
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
        authorized = _predecessor_map(wire["predecessors"])
        reference = _admit_predecessor(predecessor, authorized)
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
        destination_intent = _intent_path(root, destination, owner)
        source_present = source.exists()
        # A released container's mount preparation can recreate its old empty
        # staging path. The moved durable intent identifies the surviving tree.
        if destination_intent.exists() and _empty_staging(source):
            source_present = False
        intent_path = _intent_path(root, source if source_present else destination, owner)
        intent = {"schema_version": 1, "source": reference, "destination": owner}
        recorded = intent_path.exists()
        if recorded and _read(intent_path) != intent:
            raise QueueConflictError("staging continuation replay conflicts")

        if source_present:
            _admit_source_marker(root, source, _read(source / RECEIPT), reference, authorized)
            if destination.exists():
                marker = destination / RECEIPT
                if not _empty_staging(destination) or (
                    marker.exists() and _read(marker) != {"schema_version": 1, "identity": owner}
                ):
                    raise QueueConflictError("staging continuation destination contains output")
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
            _admit_source_marker(root, destination, marker, reference, authorized)
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


def _grant_receipt(request: PublicationRequest, agent_id: str, fence: str):
    wire = recovery.validate_wire(request)
    if wire is None:
        if requested(request):
            raise QueueConflictError("staging continuation grant lacks recovery delivery")
        return None
    predecessor = validate_binding(request, wire)
    if predecessor is None:
        return None
    owner = identity(request, agent_id=agent_id, fence=fence)
    data = encoded({"schema_version": 1, "source": predecessor, "destination": owner}).decode()
    return predecessor, owner, hashlib.sha256(data.encode()).hexdigest(), data


def require_grant_continuation(request: PublicationRequest, conn: Any, *, agent_id: str, fence: str) -> None:
    """Refuse a start permit until its selected handoff is durably acknowledged."""
    require_grant_receipt(conn, request.assignment_id, expected_grant_receipt(request, agent_id, fence))


def expected_grant_receipt(request: PublicationRequest, agent_id: str, fence: str) -> tuple[str, str] | None:
    receipt = _grant_receipt(request, agent_id, fence)
    return None if receipt is None else (receipt[2], receipt[3])


def require_grant_receipt(conn: Any, assignment_id: str, expected: tuple[str, str] | None) -> None:
    if expected is None:
        return
    previous = conn.execute(_GRANT_QUERY, (_PRINCIPAL, assignment_id)).fetchone()
    if previous is None or tuple(previous) != expected:
        raise QueueConflictError("staging continuation is not acknowledged for this grant")


def finish_grant_continuation(
    request: PublicationRequest,
    roots: Mapping[str, PlainData],
    *,
    agent_id: str,
    fence: str,
    connection: Callable[[], Any],
    require_live_owner: Callable[[], Mapping[str, PlainData]],
) -> None:
    """Finish staging before returning a native grant, with durable replay.

    The caller serializes this operation against release of the same assignment.
    Its receipt precedes grant acknowledgement, so a later grant RPC never
    mutates staging already exposed to a running worker. The filesystem intent
    still owns recovery if the control receipt was not committed.
    """
    expected = _grant_receipt(request, agent_id, fence)
    if expected is None:
        return
    predecessor, owner, digest, data = expected
    parameters = (_PRINCIPAL, request.assignment_id)
    with connection() as conn:
        previous = conn.execute(_GRANT_QUERY, parameters).fetchone()
    if previous is not None:
        if tuple(previous) != (digest, data):
            raise QueueConflictError("staging grant receipt conflicts")
        return
    continue_staging(request, roots, predecessor=predecessor, agent_id=agent_id,
                     fence=fence, require_live_owner=require_live_owner)
    if require_live_owner() != owner:
        raise QueueConflictError("staging grant authority changed before acknowledgement")
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        previous = conn.execute(_GRANT_QUERY, parameters).fetchone()
        if previous is not None and tuple(previous) != (digest, data):
            raise QueueConflictError("staging grant receipt conflicts")
        conn.execute(
            "INSERT OR IGNORE INTO agent_receipts "
            "(principal_id, operation, idempotency_key, digest, result_json) VALUES (?, 'continue_staging', ?, ?, ?)",
            (*parameters, digest, data),
        )
        conn.commit()
