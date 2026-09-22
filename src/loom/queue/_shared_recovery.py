"""Assignment-owned recovery trees sealed only at native provider release.

The coordinator receipt is a retention reference, never a successful output or
scientific eligibility record. Existing publication IO owns bounded inventories,
no-link containment, checksums, and cleanup protection.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any, cast

from loom.pipeline.stores.atomic import atomic_write_bytes
from loom.pipeline.stores.shared_artifacts import (
    RECEIPT,
    budgets,
    contained,
    encoded,
    inventory,
    receipt_bytes,
    relative,
)
from loom.serialization import PlainData, thaw_plain_data
from .errors import QueueConflictError
from ._shared_publication import identity, publication_id, selected, staging_relative

WIRE = "loom.remote_recovery"
BINDING = "loom.recovery_binding"
_PRINCIPAL = "native-shared-recovery"


def current_relative(request: Any, agent_id: str) -> str:
    return str(
        PurePosixPath(staging_relative(request, agent_id)).parent.parent / "recovery"
    )


def _reference(value: object) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or set(value)
        != {
            "schema_version",
            "root_id",
            "tree",
            "publication_id",
            "receipt_digest",
            "budgets",
            "identity",
        }
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
    ):
        raise QueueConflictError("recovery reference schema conflicts")
    result = cast(dict[str, Any], thaw_plain_data(value))
    relative(result["root_id"])
    relative(result["tree"])
    budgets(result["budgets"])
    for key in ("publication_id", "receipt_digest"):
        if (
            not isinstance(result[key], str)
            or len(result[key]) != 64
            or any(c not in "0123456789abcdef" for c in result[key])
        ):
            raise QueueConflictError("recovery reference digest conflicts")
    owner = result["identity"]
    if (
        not isinstance(owner, dict)
        or set(owner)
        != {
            "assignment_id",
            "attempt_id",
            "stage_name",
            "attempt",
            "agent_id",
            "fence",
            "origin_run_id",
        }
        or any(
            not isinstance(owner[key], str) or not owner[key]
            for key in (
                "assignment_id",
                "attempt_id",
                "stage_name",
                "agent_id",
                "fence",
                "origin_run_id",
            )
        )
        or type(owner["attempt"]) is not int
        or owner["attempt"] < 1
        or publication_id(owner) != result["publication_id"]
    ):
        raise QueueConflictError("recovery reference ownership conflicts")
    if result["tree"] != f"loom-recovery-retained/{result['publication_id']}":
        raise QueueConflictError("recovery reference tree conflicts")
    return result


def validate_wire(request: Any) -> dict[str, Any] | None:
    raw = request.worker_metadata.get(WIRE)
    if raw is None:
        return None
    selection = selected(request)
    if (
        selection is None
        or request.preparation_input is not None
        or not isinstance(raw, Mapping)
        or set(raw) != {"schema_version", "root_id", "tree", "predecessors"}
    ):
        raise QueueConflictError("remote recovery binding conflicts")
    value = cast(dict[str, Any], thaw_plain_data(raw))
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["root_id"] != selection[0]
        or not isinstance(value["predecessors"], list)
    ):
        raise QueueConflictError("remote recovery ownership conflicts")
    parts = PurePosixPath(relative(value["tree"])).parts
    if (
        len(parts) != 5
        or parts[0] != "loom-work"
        or len(parts[1]) != 64
        or any(c not in "0123456789abcdef" for c in parts[1])
        or parts[2:] != (request.assignment_id, request.attempt_id, "recovery")
    ):
        raise QueueConflictError("remote recovery ownership conflicts")
    execution = request.worker_metadata["loom.execution_binding"]
    previous = 0
    for raw_ref in value["predecessors"]:
        ref = _reference(raw_ref)
        owner = ref["identity"]
        if (
            ref["root_id"] != selection[0]
            or ref["budgets"] != selection[1]["publication"]
            or owner.get("origin_run_id") != execution["origin_run_id"]
            or owner.get("stage_name") != request.stage_name
            or type(owner.get("attempt")) is not int
            or not previous < owner["attempt"] < request.attempt
        ):
            raise QueueConflictError("recovery predecessor ownership conflicts")
        previous = owner["attempt"]
    return value


def bind_delivery(
    request: Any,
    conn: Any,
    run_uri: str,
    roots: Mapping[str, PlainData],
    *,
    session_id: str,
) -> Any:
    selection = selected(request)
    if selection is None or request.preparation_input is not None:
        return request
    session = conn.execute(
        "SELECT agent_root_id FROM agent_sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if session is None:
        raise QueueConflictError("recovery destination machine is unavailable")
    predecessors = []
    rows = conn.execute(
        "SELECT r.*, d.request_json, a.result_json AS recovery_json FROM remote_assignments r "
        "JOIN agent_deliveries d USING(assignment_id) LEFT JOIN agent_receipts a "
        "ON a.principal_id = ? AND a.operation = 'seal' AND a.idempotency_key = r.assignment_id "
        "WHERE r.run_uri = ? AND r.stage_name = ? AND r.attempt < ? "
        "AND r.start_permitted = 1 ORDER BY r.attempt",
        (_PRINCIPAL, run_uri, request.stage_name, request.attempt),
    ).fetchall()
    # Declined/revoked deliveries with no start permit cannot own progress.
    for row in rows:
        if WIRE not in json.loads(row["request_json"])["worker_metadata"]:
            continue
        if (
            row["state"] != "RELEASED"
            or row["provider_release_proof_json"] is None
            or row["recovery_json"] is None
        ):
            raise QueueConflictError(
                "recovery predecessor is not positively settled and retained"
            )
        report = None if row["report_json"] is None else json.loads(row["report_json"])
        if report is not None and report["status"] != "FAILED":
            continue
        ref = _reference(json.loads(row["recovery_json"]))
        if (
            ref["identity"]["assignment_id"] != row["assignment_id"]
            or ref["identity"]["fence"] != row["fence"]
        ):
            raise QueueConflictError("recovery retained ownership is obsolete")
        resolve(ref, roots)
        predecessors.append(ref)
    result = replace(
        request,
        worker_metadata={
            **request.worker_metadata,
            WIRE: {
                "schema_version": 1,
                "root_id": selection[0],
                "tree": current_relative(request, session["agent_root_id"]),
                "predecessors": predecessors,
            },
        },
    )
    validate_wire(result)
    return result


def _owner(request: Any, agent_id: str, fence: str) -> dict[str, PlainData]:
    return {
        **identity(request, agent_id=agent_id, fence=fence),
        "origin_run_id": request.worker_metadata["loom.execution_binding"][
            "origin_run_id"
        ],
    }


def current_tree(
    request: Any,
    roots: Mapping[str, PlainData],
    *,
    owner: Mapping[str, PlainData] | None = None,
    agent_id: str | None = None,
) -> Path:
    value = validate_wire(request)
    assert value is not None
    machine = str(owner["agent_id"]) if owner is not None else agent_id
    if machine is not None and value["tree"] != current_relative(request, machine):
        raise QueueConflictError("recovery destination machine ownership conflicts")
    root = cast(Mapping[str, PlainData], roots[value["root_id"]])
    selection = selected(request)
    assert selection is not None
    if root["access"] != "rw" or root.get("publication") != selection[1]["publication"]:
        raise QueueConflictError("recovery root qualification conflicts")
    tree = contained(Path(str(root["host_path"])), value["tree"], exists=False)
    if owner is not None:
        tree.mkdir(parents=True, exist_ok=True)
        marker = tree / RECEIPT
        data = encoded({"schema_version": 1, "identity": owner})
        if marker.exists():
            if (
                receipt_bytes(
                    marker, budgets(root["publication"])["max_manifest_bytes"]
                )
                != data
            ):
                raise QueueConflictError("recovery writable ownership conflicts")
        else:
            atomic_write_bytes(marker, data)
    return tree


def resolve(value: object, roots: Mapping[str, PlainData]) -> Path:
    ref = _reference(value)
    root = roots.get(ref["root_id"])
    if not isinstance(root, Mapping) or root.get("publication") != ref["budgets"]:
        raise QueueConflictError("recovery predecessor root is not admitted")
    tree = contained(Path(str(root["host_path"])), ref["tree"])
    data = receipt_bytes(contained(tree, RECEIPT), ref["budgets"]["max_manifest_bytes"])
    if hashlib.sha256(data).hexdigest() != ref["receipt_digest"]:
        raise QueueConflictError("recovery receipt integrity conflicts")
    receipt = json.loads(data)
    if receipt != {
        "schema_version": 1,
        "publication_id": ref["publication_id"],
        "identity": ref["identity"],
        "members": inventory(tree, ref["budgets"]),
    }:
        raise QueueConflictError("recovery closure integrity conflicts")
    return tree


def worker_binding(workspace: Any) -> dict[str, PlainData] | None:
    request = workspace.request()
    value = validate_wire(request)
    if value is None:
        return None
    from ._shared_publication import workspace_facts
    from .shared_execution import execution_roots

    launch, _ = workspace_facts(workspace)
    profile = workspace.shared_launch_profile()
    roots = execution_roots(
        profile.shared_roots, container=profile.container is not None
    )
    owner = _owner(request, launch["agent_id"], launch["execution_fence"])
    tree = current_tree(request, roots, owner=owner)
    return cast(
        dict[str, PlainData],
        {
            "schema_version": 1,
            "current": {
                "root_id": value["root_id"],
                "tree": value["tree"],
                "path": str(tree),
            },
            "predecessors": [
                {
                    "attempt": ref["identity"]["attempt"],
                    "path": str(resolve(ref, roots)),
                    "reference": ref,
                }
                for ref in value["predecessors"]
            ],
        },
    )


def seal(
    request: Any, roots: Mapping[str, PlainData], *, agent_id: str, fence: str
) -> dict[str, Any] | None:
    """Called by the release owner only after its positive provider proof gate."""
    value = validate_wire(request)
    if value is None:
        return None
    selection = selected(request)
    assert selection is not None
    limits = budgets(selection[1]["publication"])
    owner = _owner(request, agent_id, fence)
    pub_id = publication_id(owner)
    root = cast(Mapping[str, PlainData], roots[value["root_id"]])
    final_relative = f"loom-recovery-retained/{pub_id}"
    final = contained(Path(str(root["host_path"])), final_relative, exists=False)
    staging = current_tree(request, roots, agent_id=agent_id)
    available = final if final.exists() else staging
    if not available.exists():
        # Proven no-start/early death can have no recovery files. Retain an empty
        # owned closure; absence alone never calls this positive-release path.
        available = current_tree(request, roots, owner=owner)
    members = inventory(available, limits)
    if available == staging and not (available / RECEIPT).exists() and not members:
        # Container mount construction can create the directory before any child
        # starts. Positive settlement owns this empty, uninitialized case.
        current_tree(request, roots, owner=owner)
    data = encoded(
        {
            "schema_version": 1,
            "publication_id": pub_id,
            "identity": owner,
            "members": members,
        }
    )
    if len(data) > limits["max_manifest_bytes"]:
        raise QueueConflictError("recovery manifest exceeds admitted budget")
    marker = available / RECEIPT
    existing = receipt_bytes(
        contained(available, RECEIPT), limits["max_manifest_bytes"]
    )
    if existing != data:
        if available == final or existing != encoded(
            {"schema_version": 1, "identity": owner}
        ):
            raise QueueConflictError("recovery seal ownership or replay conflicts")
        atomic_write_bytes(marker, data)
    if available != final:
        from ._remote_stage_execution import _fsync_directory

        for directory, _, files in os.walk(staging, topdown=False):
            for name in files:
                descriptor = os.open(
                    Path(directory) / name, os.O_RDONLY | os.O_NOFOLLOW
                )
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            _fsync_directory(Path(directory))
        final.parent.mkdir(parents=True, exist_ok=True)
        os.rename(staging, final)
    # The rename can have completed before an interrupted caller synced either
    # parent. Repeat both barriers on replay before retaining its reference.
    from ._remote_stage_execution import _fsync_directory

    _fsync_directory(final.parent)
    _fsync_directory(final.parent.parent)
    _fsync_directory(staging.parent)
    ref = {
        "schema_version": 1,
        "root_id": value["root_id"],
        "tree": final_relative,
        "publication_id": pub_id,
        "receipt_digest": hashlib.sha256(data).hexdigest(),
        "budgets": limits,
        "identity": owner,
    }
    resolve(ref, roots)
    # Container predecessors are mounted ro; ordinary host workers also receive
    # non-writable members. Deliberate same-UID chmod is outside the installed
    # worker trust boundary, just as deliberate publication tampering is.
    for directory, _, files in os.walk(final, topdown=False):
        for name in files:
            path = Path(directory) / name
            path.chmod(path.stat().st_mode & ~0o222)
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        path = Path(directory)
        path.chmod(path.stat().st_mode & ~0o222)
        from ._remote_stage_execution import _fsync_directory

        _fsync_directory(path)
    return ref


def retain_released(
    conn: Any, row: Any, request: Any, roots: Mapping[str, PlainData], *, agent_id: str
) -> None:
    if row["provider_release_proof_json"] is None:
        raise QueueConflictError(
            "recovery seal requires positive provider release proof"
        )
    ref = seal(request, roots, agent_id=agent_id, fence=row["fence"])
    if ref is None:
        return
    data = encoded(ref).decode()
    prior = conn.execute(
        "SELECT result_json FROM agent_receipts WHERE principal_id = ? AND operation = 'seal' AND idempotency_key = ?",
        (_PRINCIPAL, request.assignment_id),
    ).fetchone()
    if prior is not None and prior["result_json"] != data:
        raise QueueConflictError("recovery retention reference replay conflicts")
    conn.execute(
        "INSERT OR IGNORE INTO agent_receipts(principal_id, operation, idempotency_key, digest, result_json) VALUES (?, 'seal', ?, ?, ?)",
        (_PRINCIPAL, request.assignment_id, ref["receipt_digest"], data),
    )
