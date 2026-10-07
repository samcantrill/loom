"""Coordinator-owned maintenance acceptance and exact operator intents.

The caller holds the cycle lock and acceptance transaction. Accepted preparation
ownership, never caller tags, carries continuation across the closed gate.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
import sqlite3
from typing import TYPE_CHECKING, Any, cast

from loom.serialization import PlainData
from .errors import QueueConflictError, QueueServiceError, QueueError
from .operations import control_intent_digest

if TYPE_CHECKING:
    from .local_daemon import LocalDaemon, LocalDaemonConfig, LocalDaemonPrincipal
    from .local_daemon_execution import ManagedLocalIntent

MAINTENANCE_CAPABILITY = "maintenance-admission-v1"
_KEY = "maintenance-gate"
_PREFIX = "maintenance-control:"


class MaintenanceCheckConflict(QueueConflictError):
    """An accepted check composed work outside its exact operator permission."""


class MaintenanceInProgress(QueueError):
    """Definitive refusal, without a retained acceptance or work effect."""

    def __init__(self, operation_id: str, maintenance_id: str) -> None:
        super().__init__("maintenance_in_progress")
        self.code = "maintenance_in_progress"
        self.ids = {"operation_id": operation_id, "maintenance_id": maintenance_id}
        self.operation_id = operation_id
        self.maintenance_id = maintenance_id


def initialize(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO daemon_metadata(key, value) VALUES (?, ?)",
        (
            _KEY,
            json.dumps(
                {
                    "state": "open",
                    "revision": 0,
                    "maintenance_id": None,
                    "intent_digest": None,
                    "coordinator_id": None,
                    "checks": {},
                }
            ),
        ),
    )


def _read(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        "SELECT value FROM daemon_metadata WHERE key = ?", (_KEY,)
    ).fetchone()
    if row is None:
        raise QueueServiceError("maintenance state is unavailable")
    return cast(dict[str, Any], json.loads(row[0]))


def observe(daemon: LocalDaemon) -> dict[str, PlainData]:
    from ._service_lifetime import _retained_coordinator_operations
    with daemon._cycle_lock, daemon._connection() as conn:
        state = _read(conn)
        waits = []
        if _retained_coordinator_operations(conn):
            waits.append("accepted_work_or_preparation")
        if conn.execute("SELECT 1 FROM agent_coordinator_references WHERE resolved = 0 LIMIT 1").fetchone():
            waits.append("assignment_publication_or_claim_release")
        if conn.execute("SELECT 1 FROM agent_controls WHERE state IN ('pending_delivery','applying') OR acknowledged = 0 LIMIT 1").fetchone():
            waits.append("agent_control_settlement")
        if daemon._service_error is not None:
            waits.append("coordinator_reconciliation_unavailable")
    return {
        **state,
        "settled": not waits,
        "wait_reasons": waits,
        "coordinator_id": daemon._require_started(),
        "owner": daemon._require_started(),
        "observed_at": daemon._clock(),
        "freshness": "current",
        "availability": "available",
    }


def _id(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError("maintenance identity is invalid")
    return value


def validate_control(value: Mapping[str, object]) -> dict[str, PlainData]:
    fields = {
        "operation_id",
        "maintenance_id",
        "maintenance_intent_digest",
        "action",
        "expected_revision",
        "check",
    }
    if set(value) != fields:
        raise ValueError("maintenance control fields are invalid")
    for name in ("operation_id", "maintenance_id", "maintenance_intent_digest"):
        _id(value[name])
    revision = value["expected_revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("maintenance revision is invalid")
    action = value["action"]
    if action not in {"close", "open", "authorize", "revoke"}:
        raise ValueError("maintenance action is invalid")
    check = value["check"]
    if action == "authorize":
        if not isinstance(check, Mapping):
            raise ValueError("maintenance check is missing")
        validate_check(check)
    elif action == "revoke":
        _id(check)
    elif check is not None:
        raise ValueError("maintenance check is unexpected")
    return cast(dict[str, PlainData], json.loads(json.dumps(value)))


def validate_check(check: Mapping[str, object]) -> None:
    from .run import RunRequest
    from ._remote_stage_execution import ResidentProfileDescriptor
    from loom.pipeline.resources import ResourceRequest

    if set(check) != {
        "request",
        "principal_id",
        "agent_id",
        "pool",
        "profile",
        "resources",
        "preparation_resources",
        "max_stages",
        "previous_check_id",
    }:
        raise ValueError("maintenance check fields are invalid")
    for name in ("principal_id", "agent_id", "pool"):
        _id(check[name])
    if check["previous_check_id"] is not None:
        _id(check["previous_check_id"])
    if not isinstance(check["request"], Mapping):
        raise ValueError("maintenance check request is invalid")
    request = RunRequest.from_dict(check["request"])
    if request.mode != "exact" or request.fresh_stages:
        raise ValueError("maintenance check requires an exact fresh native request")
    ResidentProfileDescriptor.from_dict(cast(Mapping[str, object], check["profile"]))
    ResourceRequest.from_dict(check["resources"])
    ResourceRequest.from_dict(check["preparation_resources"])
    count = check["max_stages"]
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("maintenance check stage bound is invalid")


def mutate(
    daemon: LocalDaemon,
    principal: LocalDaemonPrincipal,
    control: Mapping[str, object],
    expected_coordinator_id: str,
) -> dict[str, PlainData]:
    value = validate_control(control)
    check = value["check"]
    daemon._authorizer().require_operator(principal, "maintenance")
    if isinstance(check, Mapping):
        daemon._authorizer().require_operator(
            principal,
            "maintenance",
            agent_id=cast(str, check["agent_id"]),
            pool=cast(str, check["pool"]),
        )
    if expected_coordinator_id != daemon._require_started():
        raise QueueConflictError("maintenance coordinator identity conflicts")
    digest = control_intent_digest(
        {**value, "expected_coordinator_id": expected_coordinator_id}
    )
    key = _PREFIX + cast(str, value["operation_id"])
    with daemon._cycle_lock, daemon._connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT value FROM daemon_metadata WHERE key = ?", (key,)
        ).fetchone()
        if existing is not None:
            record = json.loads(existing[0])
            if record["intent_digest"] != digest:
                raise QueueConflictError("maintenance operation intent conflicts")
            return cast(dict[str, PlainData], record)
        state = _read(conn)
        if state["revision"] != value["expected_revision"]:
            raise QueueConflictError("maintenance gate revision conflicts")
        if value["action"] == "close":
            prior_owner = conn.execute(
                "SELECT json_extract(value, '$.control.maintenance_intent_digest') FROM daemon_metadata "
                "WHERE key LIKE 'maintenance-control:%' AND json_extract(value, '$.control.action') = 'close' "
                "AND json_extract(value, '$.control.maintenance_id') = ? LIMIT 1",
                (value["maintenance_id"],),
            ).fetchone()
            if (
                prior_owner is not None
                and prior_owner[0] != value["maintenance_intent_digest"]
            ):
                raise QueueConflictError("maintenance owner intent conflicts")
            if state["state"] != "open":
                raise QueueConflictError("maintenance gate is already owned")
            state.update(
                state="closed",
                maintenance_id=value["maintenance_id"],
                intent_digest=value["maintenance_intent_digest"],
                coordinator_id=expected_coordinator_id,
            )
        else:
            if (
                state["state"] != "closed"
                or state["maintenance_id"] != value["maintenance_id"]
                or state["intent_digest"] != value["maintenance_intent_digest"]
            ):
                raise QueueConflictError("maintenance gate ownership conflicts")
            if value["action"] == "open":
                if state["checks"]:
                    raise QueueConflictError(
                        "maintenance check permission must be removed"
                    )
                state.update(state="open", maintenance_id=None, intent_digest=None)
            elif value["action"] == "authorize":
                assert isinstance(check, Mapping)
                from .run import RunRequest

                request = RunRequest.from_dict(
                    cast(Mapping[str, object], check["request"])
                )
                check_id = request.preparation.operation_id
                if check_id in state["checks"]:
                    raise QueueConflictError(
                        "maintenance check identity is already authorized"
                    )
                policy = daemon.config.preparation_policy
                selected_profile = (
                    None
                    if policy is None
                    else policy.select(request.preparation)["profile"]
                )
                if (
                    not isinstance(selected_profile, Mapping)
                    or selected_profile["profile_descriptor"] != check["profile"]
                ):
                    raise QueueConflictError("maintenance check profile conflicts")
                retained_key = "maintenance-check:" + check_id
                retained = conn.execute(
                    "SELECT value FROM daemon_metadata WHERE key = ?", (retained_key,)
                ).fetchone()
                binding = {
                    "maintenance_id": value["maintenance_id"],
                    "check": dict(check),
                }
                if retained is not None and json.loads(retained[0]) != binding:
                    raise QueueConflictError(
                        "maintenance check identity intent conflicts"
                    )
                previous = check["previous_check_id"]
                if previous is not None:
                    prior = conn.execute(
                        "SELECT value FROM daemon_metadata WHERE key = ?",
                        ("maintenance-check:" + cast(str, previous),),
                    ).fetchone()
                    if prior is None:
                        raise QueueConflictError(
                            "previous maintenance check is unknown"
                        )
                    prior_binding = json.loads(prior[0])
                    slots = (
                        "agent_id",
                        "pool",
                        "profile",
                        "resources",
                        "preparation_resources",
                        "max_stages",
                    )
                    if prior_binding["maintenance_id"] != value[
                        "maintenance_id"
                    ] or any(
                        prior_binding["check"][field] != check[field] for field in slots
                    ):
                        raise QueueConflictError(
                            "successor maintenance check target conflicts"
                        )
                conn.execute(
                    "INSERT OR IGNORE INTO daemon_metadata(key, value) VALUES (?, ?)",
                    (retained_key, json.dumps(binding)),
                )
                state["checks"][check_id] = dict(check)
            else:
                state["checks"].pop(cast(str, check), None)
        state["revision"] += 1
        receipt: dict[str, PlainData] = {
            "operation_id": value["operation_id"],
            "intent_digest": digest,
            "control": value,
            "gate": state,
            "mutation_outcome": "applied",
        }
        conn.execute(
            "UPDATE daemon_metadata SET value = ? WHERE key = ?",
            (json.dumps(state), _KEY),
        )
        conn.execute(
            "INSERT INTO daemon_metadata(key, value) VALUES (?, ?)",
            (key, json.dumps(receipt)),
        )
        conn.commit()
    return receipt


def operation(daemon: LocalDaemon, operation_id: str) -> dict[str, PlainData]:
    with daemon._connection() as conn:
        row = conn.execute(
            "SELECT value FROM daemon_metadata WHERE key = ?", (_PREFIX + operation_id,)
        ).fetchone()
    if row is None:
        raise QueueServiceError("managed operation was not found")
    return cast(dict[str, PlainData], json.loads(row[0]))


def classify(
    conn: sqlite3.Connection,
    operation_id: str,
    *,
    request: Mapping[str, PlainData] | None = None,
    principal_id: str | None = None,
    parent_id: str | None = None,
    intent: ManagedLocalIntent | None = None,
    preparation_child: bool = False,
) -> Mapping[str, PlainData] | None:
    """Resolve fresh acceptance only; callers already resolved replay/conflict.

    A returned check binding must be retained with the accepted preparation so
    revocation removes future permission without rewriting accepted provenance.
    """
    if parent_id is not None:
        parent = conn.execute(
            "SELECT selected_json FROM preparation_operations WHERE operation_id = ?",
            (parent_id,),
        ).fetchone()
        if parent is None:
            raise QueueConflictError("accepted preparation owner is missing")
        selected = json.loads(parent[0])
        check = selected.get("maintenance_check")
        if check is not None and intent is not None:
            _check_target(check, intent, preparation_child=preparation_child)
        return None
    state = _read(conn)
    if state["state"] == "open":
        return None
    check = state["checks"].get(operation_id)
    if check is not None:
        if check["principal_id"] != principal_id or check["request"] != request:
            raise QueueConflictError("maintenance check intent conflicts")
        return cast(Mapping[str, PlainData], check)
    raise MaintenanceInProgress(operation_id, state["maintenance_id"])


def _check_target(
    check: Mapping[str, Any], intent: ManagedLocalIntent, *, preparation_child: bool
) -> None:
    from loom.pipeline.orchestration import ExecutionRequirement

    profile = check["profile"]
    requirement = ExecutionRequirement(
        profile["project_fingerprint"],
        profile["environment_fingerprint"],
        profile["executor_fingerprint"],
    )
    if len(intent.pipeline.stages) > (1 if preparation_child else check["max_stages"]):
        raise MaintenanceCheckConflict("maintenance check exceeds stage bound")
    for name, placement in intent.placements.items():
        if (
            placement.target != check["agent_id"]
            or placement.pool_name != check["pool"]
            or placement.resource_request.to_dict()
            != check["preparation_resources" if preparation_child else "resources"]
            or intent.execution_requirements[name] != requirement
        ):
            raise MaintenanceCheckConflict(
                "maintenance check target constraints conflict"
            )


def preparation_placement(
    config: LocalDaemonConfig, operation_id: str
) -> Mapping[str, PlainData] | None:
    """Return only the accepted operator selection for the fixed native child.

    Standalone preparation producers have no accepted coordinator parent. A
    retained check parent pins its internal child without changing project input
    or introducing placement fields into the worker's preparation-input codec.
    """
    if not config.control_database.is_file():
        return None
    with sqlite3.connect(
        f"{config.control_database.resolve().as_uri()}?mode=ro", uri=True
    ) as conn:
        row = conn.execute(
            "SELECT selected_json FROM preparation_operations WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
    if row is None:
        return None
    check = json.loads(row[0]).get("maintenance_check")
    return (
        None if check is None else {"target": check["agent_id"], "pool": check["pool"]}
    )
