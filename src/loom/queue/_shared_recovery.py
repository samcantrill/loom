"""Assignment-owned recovery trees sealed only at native provider release.

The coordinator receipt is a retention reference, never a successful output or
scientific eligibility record. Existing publication IO owns bounded inventories,
no-link containment, checksums, and cleanup protection.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any, cast

from loom.pipeline.stores.atomic import atomic_write_bytes
from loom.pipeline.stores.shared_artifacts import (
    RECEIPT,
    SharedPublicationBudgetExceeded,
    budgets,
    publication_policy,
    publication_configuration,
    TRUSTED_SHARED_STORAGE,
    admits_budgets,
    check_budget,
    contained,
    encoded,
    inventory,
    receipt_bytes,
    relative,
)
from loom.serialization import PlainData, thaw_plain_data
from .errors import QueueConflictError
from ._shared_publication import identity, publication_id, selected, attempt_relative

WIRE = "loom.remote_recovery"
BINDING = "loom.recovery_binding"
_PRINCIPAL = "native-shared-recovery"


def current_relative(request: Any, agent_id: str) -> str:
    return str(
        PurePosixPath(attempt_relative(request, agent_id)) / "recovery"
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
        or value["schema_version"] not in (1, 2)
    ):
        raise QueueConflictError("recovery reference schema conflicts")
    result = cast(dict[str, Any], thaw_plain_data(value))
    relative(result["root_id"])
    relative(result["tree"])
    budgets(result["budgets"])
    if (result["schema_version"] == 2) != (publication_policy(result["budgets"]) == TRUSTED_SHARED_STORAGE):
        raise QueueConflictError("recovery policy and schema conflict")
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
            or not admits_budgets(selection[1]["publication"], ref["budgets"])
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
    slurm_assignments: Any = None,
    verify_trees: bool = True,
) -> Any:
    selection = selected(request)
    if selection is None or request.preparation_input is not None:
        return request
    session = conn.execute(
        "SELECT agent_root_id FROM agent_sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if session is None:
        raise QueueConflictError("recovery destination machine is unavailable")
    return _bind_delivery(
        request, conn, run_uri, roots, agent_id=session["agent_root_id"],
        slurm_assignments=slurm_assignments, verify_trees=verify_trees,
    )


def assignment_rows(
    conn: Any, run_uri: str, *, slurm_assignments: Any = None,
    stage_name: str | None = None, limit: int | None = None,
) -> list[dict[str, Any]]:
    """Project both native providers into the existing recovery retention contract."""
    rows = conn.execute(
        "SELECT r.*, d.request_json, a.result_json AS recovery_json, "
        "f.result_json AS recovery_failure_json FROM remote_assignments r "
        "LEFT JOIN agent_deliveries d USING(assignment_id) LEFT JOIN agent_receipts a "
        "ON a.principal_id = ? AND a.operation = 'seal' AND a.idempotency_key = r.assignment_id "
        "LEFT JOIN agent_receipts f ON f.principal_id = ? AND f.operation = 'seal_unavailable' "
        "AND f.idempotency_key = r.assignment_id "
        "WHERE r.run_uri = ? AND (? IS NULL OR r.stage_name = ?) "
        "ORDER BY r.stage_name, r.attempt LIMIT ?",
        (_PRINCIPAL, _PRINCIPAL, run_uri, stage_name, stage_name, -1 if limit is None else limit + 1),
    ).fetchall()
    result = [dict(row) for row in rows]
    if slurm_assignments is not None:
        for record, evidence in slurm_assignments.recovery_records(run_uri, stage_name=stage_name, limit=limit):
            assignment = record.assignment
            receipts = {receipt["operation"]: receipt["result_json"] for receipt in conn.execute(
                "SELECT operation, result_json FROM agent_receipts WHERE principal_id = ? "
                "AND operation IN ('seal', 'seal_unavailable') AND idempotency_key = ?",
                (_PRINCIPAL, assignment.assignment_id),
            )}
            proof = (
                evidence.get("release") if evidence is not None
                and evidence.get("provider_released") is True else None
            )
            result.append({
                "assignment_id": assignment.assignment_id,
                "run_uri": assignment.run_uri, "stage_name": assignment.stage_name,
                "attempt_id": assignment.attempt_id, "attempt": assignment.attempt,
                "agent_id": assignment.agent_id,
                "state": record.state.upper(), "fence": record.fence,
                "start_permitted": record.start_consumed,
                "request_json": encoded(record.delivery.to_dict()).decode(),
                "report_json": None if record.report is None else encoded(record.report.to_dict()).decode(),
                "provider_release_proof_json": None if proof is None else encoded(proof).decode(),
                "recovery_json": receipts.get("seal"),
                "recovery_failure_json": receipts.get("seal_unavailable"),
            })
    if limit is not None and len(result) > limit:
        raise QueueConflictError("recovery history exceeds assignment limit")
    return sorted(result, key=lambda row: (row["stage_name"], row["attempt"]))


def bind_slurm_delivery(
    request: Any, conn: Any, run_uri: str, roots: Mapping[str, PlainData], *,
    agent_id: str, slurm_assignments: Any, verify_trees: bool = True,
) -> Any:
    if selected(request) is None or request.preparation_input is not None:
        return request
    return _bind_delivery(
        request, conn, run_uri, roots, agent_id=agent_id,
        slurm_assignments=slurm_assignments, verify_trees=verify_trees,
    )


def _bind_delivery(
    request: Any, conn: Any, run_uri: str, roots: Mapping[str, PlainData], *,
    agent_id: str, slurm_assignments: Any, verify_trees: bool = True,
) -> Any:
    selection = selected(request)
    assert selection is not None
    predecessors = []
    rows = assignment_rows(conn, run_uri, slurm_assignments=slurm_assignments, stage_name=request.stage_name)
    # Declined/revoked deliveries with no start permit cannot own progress.
    for row in rows:
        if (row["stage_name"] != request.stage_name or row["attempt"] >= request.attempt
            or not row["start_permitted"] or row["request_json"] is None):
            continue
        if WIRE not in json.loads(row["request_json"])["worker_metadata"]:
            continue
        if row["recovery_failure_json"] is not None:
            raise QueueConflictError("recovery predecessor unavailable: retention budget exceeded")
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
        released = conn.execute(
            "SELECT 1 FROM agent_receipts WHERE principal_id = ? "
            "AND operation = 'release_recovery' AND idempotency_key = ?",
            (_PRINCIPAL, row["assignment_id"]),
        ).fetchone()
        if released is not None:
            raise QueueConflictError("recovery predecessor has been reserved for cleanup")
        ref = _reference(json.loads(row["recovery_json"]))
        if (
            ref["identity"]["assignment_id"] != row["assignment_id"]
            or ref["identity"]["fence"] != row["fence"]
        ):
            raise QueueConflictError("recovery retained ownership is obsolete")
        if verify_trees:
            resolve(ref, roots)
        predecessors.append(ref)
    result = replace(
        request,
        worker_metadata={
            **request.worker_metadata,
            WIRE: {
                "schema_version": 1,
                "root_id": selection[0],
                "tree": current_relative(request, agent_id),
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
    if root["access"] != "rw" or not admits_budgets(root.get("publication"), selection[1]["publication"]):
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


def inspect(value: object, roots: Mapping[str, PlainData]) -> tuple[Path, dict[str, Any]]:
    """Inspect a sealed recovery inventory without reading its payload files.

    Used for cleanup planning and byte estimates, not for admitting restart
    state. The coordinator seal pins the inventory digest and assignment owner.
    Recovery consumers use ``resolve`` for the recorded policy: full byte
    verification for schema 1, ownership-only admission for trusted schema 2.
    Trusted receipts have ``members=None`` and no measured payload byte count.
    """
    ref = _reference(value)
    root = roots.get(ref["root_id"])
    if not isinstance(root, Mapping) or not admits_budgets(root.get("publication"), ref["budgets"]):
        raise QueueConflictError("recovery predecessor root is not admitted")
    tree = contained(Path(str(root["host_path"])), ref["tree"])
    data = receipt_bytes(contained(tree, RECEIPT), ref["budgets"]["max_manifest_bytes"])
    if hashlib.sha256(data).hexdigest() != ref["receipt_digest"]:
        raise QueueConflictError("recovery receipt integrity conflicts")
    receipt = json.loads(data)
    if (
        not isinstance(receipt, dict)
        or set(receipt) != {"schema_version", "publication_id", "identity", "members"}
        or receipt["schema_version"] != ref["schema_version"]
        or receipt["publication_id"] != ref["publication_id"]
        or receipt["identity"] != ref["identity"]
        or (ref["schema_version"] == 2 and receipt["members"] is not None)
        or (ref["schema_version"] == 1 and (
            not isinstance(receipt["members"], list)
            or len(receipt["members"]) > ref["budgets"]["max_members"]
        ))
    ):
        raise QueueConflictError("recovery receipt ownership conflicts")
    # The bounded inventory was produced and pinned by the native seal owner.
    # Its payload is deliberately not reopened just to estimate reclaimable bytes.
    return tree, receipt


def resolve(value: object, roots: Mapping[str, PlainData]) -> Path:
    ref = _reference(value)
    tree, receipt = inspect(ref, roots)
    if ref["schema_version"] == 1 and receipt["members"] != inventory(tree, ref["budgets"]):
        raise QueueConflictError("recovery closure integrity conflicts")
    return tree


def worker_binding(workspace: Any, *, profile: Any = None) -> dict[str, PlainData] | None:
    request = workspace.request()
    value = validate_wire(request)
    if value is None:
        return None
    from ._shared_publication import workspace_facts
    from .shared_execution import execution_roots

    launch, _ = workspace_facts(workspace)
    if profile is None:
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
    limits = publication_configuration(selection[1]["publication"])
    trusted = publication_policy(limits) == TRUSTED_SHARED_STORAGE
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
    members = None if trusted else inventory(available, limits)
    if (available == staging and not (available / RECEIPT).exists()
            and (not any(available.iterdir()) if trusted else not members)):
        # Container mount construction can create the directory before any child
        # starts. Positive settlement owns this empty, uninitialized case.
        current_tree(request, roots, owner=owner)
    data = encoded(
        {
            "schema_version": 2 if trusted else 1,
            "publication_id": pub_id,
            "identity": owner,
            "members": members,
        }
    )
    check_budget("max_manifest_bytes", limits["max_manifest_bytes"], len(data))
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

        if not trusted:
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
        "schema_version": 2 if trusted else 1,
        "root_id": value["root_id"],
        "tree": final_relative,
        "publication_id": pub_id,
        "receipt_digest": hashlib.sha256(data).hexdigest(),
        "budgets": limits,
        "identity": owner,
    }
    resolve(ref, roots)
    if trusted:
        return ref
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


@dataclass(frozen=True)
class PreparedRetention:
    assignment_id: str
    operation: str
    digest: str
    result_json: str


def commit_retention(conn: Any, prepared: PreparedRetention | None) -> None:
    """Persist a prepared outcome after its caller revalidates ownership."""
    if prepared is None:
        return
    previous = conn.execute(
        "SELECT operation, digest, result_json FROM agent_receipts "
        "WHERE principal_id=? AND idempotency_key=? "
        "AND operation IN ('seal', 'seal_unavailable')",
        (_PRINCIPAL, prepared.assignment_id),
    ).fetchall()
    expected = (prepared.operation, prepared.digest, prepared.result_json)
    if any(tuple(row) != expected for row in previous):
        raise QueueConflictError("recovery retention outcome replay conflicts")
    conn.execute(
        "INSERT OR IGNORE INTO agent_receipts "
        "(principal_id, operation, idempotency_key, digest, result_json) VALUES (?, ?, ?, ?, ?)",
        (_PRINCIPAL, prepared.operation, prepared.assignment_id,
         prepared.digest, prepared.result_json),
    )


def retain_released(
    conn: Any, row: Any, request: Any, roots: Mapping[str, PlainData], *, agent_id: str
) -> None:
    commit_retention(conn, prepare_retention(conn, row, request, roots, agent_id=agent_id))


def prepare_retention(
    conn: Any, row: Any, request: Any, roots: Mapping[str, PlainData], *, agent_id: str
) -> PreparedRetention | None:
    """Perform storage IO without writing lifecycle or receipt state."""
    if row["provider_release_proof_json"] is None:
        raise QueueConflictError(
            "recovery seal requires positive provider release proof"
        )
    value = validate_wire(request)
    if value is None:
        return
    selection = selected(request)
    assert selection is not None
    owner = _owner(request, agent_id, row["fence"])
    limits = publication_configuration(selection[1]["publication"])
    binding = {
        "schema_version": 1, "root_id": value["root_id"], "tree": value["tree"],
        "identity": owner, "budgets": limits,
    }
    prior = conn.execute(
        "SELECT digest, result_json FROM agent_receipts WHERE principal_id = ? "
        "AND operation = 'seal_unavailable' AND idempotency_key = ?",
        (_PRINCIPAL, request.assignment_id),
    ).fetchone()
    sealed = conn.execute(
        "SELECT digest, result_json FROM agent_receipts WHERE principal_id = ? "
        "AND operation = 'seal' AND idempotency_key = ?",
        (_PRINCIPAL, request.assignment_id),
    ).fetchone()
    if prior is not None:
        failure = json.loads(prior["result_json"])
        reason = failure.get("reason", {})
        budget = reason.get("budget")
        if (
            sealed is not None
            or hashlib.sha256(prior["result_json"].encode()).hexdigest() != prior["digest"]
            or failure != {**binding, "reason": reason}
            or set(reason) != {"code", "budget", "limit", "observed_at_least"}
            or reason["code"] != "budget_exceeded" or budget not in limits
            or reason["limit"] != limits[budget]
            or type(reason["observed_at_least"]) is not int
            or reason["observed_at_least"] <= limits[budget]
        ):
            raise QueueConflictError("recovery unavailable outcome replay conflicts")
        return
    if sealed is not None:
        ref = _reference(json.loads(sealed["result_json"]))
        if (ref["identity"] != owner or ref["root_id"] != value["root_id"]
            or ref["budgets"] != limits or ref["receipt_digest"] != sealed["digest"]):
            raise QueueConflictError("recovery retained receipt binding conflicts")
        root = cast(Mapping[str, PlainData], roots[value["root_id"]])
        final = contained(Path(str(root["host_path"])), ref["tree"])
        manifest = receipt_bytes(contained(final, RECEIPT), limits["max_manifest_bytes"])
        if hashlib.sha256(manifest).hexdigest() != ref["receipt_digest"]:
            raise QueueConflictError("recovery retained receipt digest conflicts")
        marker = json.loads(manifest)
        if marker.get("identity") != owner or marker.get("publication_id") != ref["publication_id"]:
            raise QueueConflictError("recovery retained receipt ownership conflicts")
        # The immutable manifest binds the retained tree. Payload inventory is
        # verified when consuming recovery, not on this control replay.
        return PreparedRetention(request.assignment_id, "seal", sealed["digest"], sealed["result_json"])
    try:
        ref = seal(request, roots, agent_id=agent_id, fence=row["fence"])
    except SharedPublicationBudgetExceeded as exc:
        # A budget failure may settle resource release, never evidence integrity.
        # Only the original, exactly owned staging tree can become unavailable;
        # a changed/incomplete previously sealed tree remains a hard conflict.
        tree = current_tree(request, roots, agent_id=agent_id)
        root = cast(Mapping[str, PlainData], roots[value["root_id"]])
        final = contained(Path(str(root["host_path"])),
                          f"loom-recovery-retained/{publication_id(owner)}", exists=False)
        ownership = encoded({"schema_version": 1, "identity": owner})
        if sealed is not None or final.exists() or receipt_bytes(
            contained(tree, RECEIPT), len(ownership)
        ) != ownership:
            raise QueueConflictError("recovery unavailable outcome ownership conflicts") from exc
        failure = {**binding, "reason": {
            "code": "budget_exceeded", "budget": exc.budget, "limit": exc.limit,
            "observed_at_least": exc.observed_at_least,
        }}
        data = encoded(failure).decode()
        return PreparedRetention(
            request.assignment_id, "seal_unavailable", hashlib.sha256(data.encode()).hexdigest(), data,
        )
    if ref is None:
        return
    data = encoded(ref).decode()
    prior = conn.execute(
        "SELECT result_json FROM agent_receipts WHERE principal_id = ? AND operation = 'seal' AND idempotency_key = ?",
        (_PRINCIPAL, request.assignment_id),
    ).fetchone()
    if prior is not None and prior["result_json"] != data:
        raise QueueConflictError("recovery retention reference replay conflicts")
    return PreparedRetention(request.assignment_id, "seal", ref["receipt_digest"], data)


def retain_seal(conn: Any, request: Any, ref: Mapping[str, Any] | None) -> None:
    """Commit a previously sealed reference in the caller's short transaction."""
    if ref is not None:
        commit_retention(conn, PreparedRetention(
            request.assignment_id, "seal", ref["receipt_digest"], encoded(ref).decode(),
        ))
