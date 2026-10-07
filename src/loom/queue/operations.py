"""Read-only native operator observations and candidate-runtime probes.

Facts are independently observed; a coordinator session is not host process
ownership. These functions never initialize roots or qualify workload code.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sqlite3
from typing import TYPE_CHECKING, cast

from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.timestamps import utc_timestamp as utc_now

if TYPE_CHECKING:
    from .local_daemon import LocalDaemon

OPERATOR_CAPABILITY = "operator-observations-v1"
CONDITIONAL_CONTROL_CAPABILITY = "conditional-agent-control-v1"


@dataclass(frozen=True, slots=True)
class OperatorObservation:
    """One owner's bounded fact; timestamps are UTC and revisions owner-local.

    ``freshness`` is current, retained or unknown. Retained capacity is never
    permission to dispatch work. Unavailable observations preserve known identity
    and report a reason rather than inventing an empty result.
    """

    owner: str | None
    observed_at: str
    revision: str | None
    freshness: str
    availability: str
    value: Mapping[str, PlainData]
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", freeze_plain_data(self.value))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": 1,
            "owner": self.owner,
            "observed_at": self.observed_at,
            "revision": self.revision,
            "freshness": self.freshness,
            "availability": self.availability,
            "value": thaw_plain_data(self.value),
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> OperatorObservation:
        from loom.timestamps import parse_timestamp

        if value.get("schema_version") != 1 or not isinstance(
            value.get("value"), Mapping
        ):
            raise ValueError("operator observation is invalid")
        for key in ("owner", "revision", "reason"):
            if value.get(key) is not None and not isinstance(value[key], str):
                raise ValueError("operator observation identity is invalid")
        if value.get("freshness") not in {
            "current",
            "retained",
            "unknown",
        } or value.get("availability") not in {"available", "unavailable"}:
            raise ValueError("operator observation availability is invalid")
        timestamp = value.get("observed_at")
        if not isinstance(timestamp, str):
            raise ValueError("operator observation timestamp is invalid")
        parse_timestamp(timestamp)
        return cls(
            cast(str | None, value.get("owner")),
            timestamp,
            cast(str | None, value.get("revision")),
            cast(str, value["freshness"]),
            cast(str, value["availability"]),
            cast(Mapping[str, PlainData], value["value"]),
            cast(str | None, value.get("reason")),
        )


def _coordinator_observation(daemon: LocalDaemon) -> OperatorObservation:
    from ._maintenance import MAINTENANCE_CAPABILITY
    status = daemon.status()
    with daemon._connection() as conn:
        metadata = dict(
            conn.execute(
                "SELECT key, value FROM daemon_metadata WHERE key IN ('active_configuration_revision', 'scheduling_fingerprint')"
            )
        )
    return OperatorObservation(
        status.coordinator_id,
        status.as_of,
        metadata.get("active_configuration_revision"),
        "current",
        "available",
        {
            **status.to_dict(),
            "configuration_revision": metadata.get("active_configuration_revision"),
            "configuration_fingerprint": daemon.config.active_configuration_fingerprint,
            "scheduling_fingerprint": metadata.get("scheduling_fingerprint"),
            "capabilities": [OPERATOR_CAPABILITY, MAINTENANCE_CAPABILITY, CONDITIONAL_CONTROL_CAPABILITY, "quiescent-profile-promotion-v1"],
        },
    )


def _agent_observation(daemon: LocalDaemon, agent_id: str) -> OperatorObservation:
    from .agent_sessions import AgentOffer

    agent = daemon.agent(agent_id)
    with daemon._connection() as conn:
        session = conn.execute(
            "SELECT agent_root_id, created_at FROM agent_sessions WHERE session_id = ?",
            (agent.session_id,),
        ).fetchone()
        row = conn.execute(
            "SELECT offer_id, offer_json, accepted_at, expires_at, current FROM agent_offers WHERE session_id = ? ORDER BY rowid DESC LIMIT 1",
            (agent.session_id,),
        ).fetchone()
        control = conn.execute(
            "SELECT request_json, state, result_code, acknowledged FROM agent_controls WHERE session_id = ? ORDER BY rowid DESC LIMIT 1",
            (agent.session_id,),
        ).fetchone()
        drain_state = conn.execute(
            "SELECT json_extract(request_json, '$.kind') AS kind "
            "FROM agent_controls WHERE session_id = ? AND "
            "(json_extract(request_json, '$.kind') IN ('drain', 'reload', 'promote') OR "
            "(json_extract(request_json, '$.kind') = 'resume' "
            "AND state = 'applied' AND acknowledged = 1)) "
            "ORDER BY rowid DESC LIMIT 1",
            (agent.session_id,),
        ).fetchone()
    assert session is not None
    offer = (
        None if row is None else AgentOffer.from_value(json.loads(row["offer_json"]))
    )
    now = daemon._clock()
    connected = (
        agent.state == "ACTIVE"
        and agent.coordinator_epoch == daemon._epoch
        and row is not None
        and row["expires_at"] >= now
    )
    control_value = None if control is None else json.loads(control["request_json"])
    # Resume intent does not undo an existing drain until the agent confirms it.
    drained = drain_state is not None and drain_state["kind"] in {"drain", "reload", "promote"}
    value: dict[str, PlainData] = {
        **agent.to_dict(),
        "agent_root_id": session["agent_root_id"],
        "connected": connected,
        "drained": drained,
        "control": None
        if control is None or control_value is None
        else {
            "operation_id": control_value["operation_id"],
            "kind": control_value["kind"],
            "state": control["state"],
            "acknowledged": bool(control["acknowledged"]),
            "code": control["result_code"],
        },
        "offer": None
        if offer is None or row is None
        else {
            "offer_id": row["offer_id"],
            "owner": session["agent_root_id"],
            "freshness": "current" if connected and row["current"] and offer.availability_revision == agent.availability_revision else "retained",
            "availability": "available",
            "observed_at": row["accepted_at"],
            "expires_at": row["expires_at"],
            "revision": offer.availability_revision,
            "cpu": offer.cpu,
            "memory_bytes": offer.memory_bytes,
            "profile_identities": [
                profile.to_dict() for profile in offer.resident_profiles
            ],
            "gpu_devices": [device.to_dict() for device in offer.gpu_devices],
            "gpu_atoms": [atom.to_dict() for atom in offer.gpu_atoms],
            "reflected_claim_ids": list(offer.reflected_claim_ids),
        },
    }
    return OperatorObservation(
        daemon._require_started(),
        now,
        agent.availability_revision,
        "current" if connected else "retained",
        "available",
        value,
        None if connected else "observation_stale",
    )


def _readonly_root(root: Path) -> sqlite3.Connection:
    from .local_daemon import _validate_private_directory

    _validate_private_directory(root)
    database = root / "control.sqlite"
    if (
        database.is_symlink()
        or not database.is_file()
        or database.stat().st_uid != os.getuid()
        or database.stat().st_mode & 0o077
    ):
        raise ValueError("root database is not protected")
    conn = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def inspect_native_service(
    root: str | Path, *, expected_root_id: str | None = None
) -> OperatorObservation:
    """Inspect a protected local role's recorded process and Linux boot identity.

    A missing/legacy boot receipt cannot prove current ownership. Service-manager
    state is deliberately unavailable here; it belongs to the service manager.
    No process is started, signalled or adopted and no lock file is created.
    """
    from .errors import QueueError

    owner = expected_root_id
    try:
        with _readonly_root(Path(root)) as conn:
            metadata = dict(conn.execute("SELECT key,value FROM root_metadata"))
        owner = metadata.get("stable_id")
        state = json.loads(metadata.get("service_process", "{}"))
        if expected_root_id is not None and owner != expected_root_id:
            return OperatorObservation(
                owner, utc_now(), None, "retained", "unavailable", {}, "wrong_owner"
            )
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        live = False
        reason = "service_stopped" if state.get("stopped") else "ownership_unavailable"
        if (
            state.get("pid")
            and not state.get("stopped")
            and state.get("boot_id") == boot
        ):
            try:
                fields = (
                    Path(f"/proc/{state['pid']}/stat")
                    .read_text()
                    .rsplit(")", 1)[1]
                    .split()
                )
                live = fields[0] != "Z" and fields[19] == state.get("started")
                reason = None if live else "process_identity_changed"
            except FileNotFoundError:
                reason = "process_missing"
        return OperatorObservation(
            owner,
            utc_now(),
            state.get("started"),
            "current",
            "available",
            {
                "root_id": owner,
                "role": metadata.get("role"),
                "service_lifetime": metadata.get("service_lifetime"),
                "expected_process": state.get("pid"),
                "boot_id": boot,
                "recorded_boot_id": state.get("boot_id"),
                "ownership": "live" if live else "unproven",
                "session_id": state.get("session_id"),
                "coordinator_id": state.get("coordinator_id"),
                "service_manager": "unavailable",
                "capabilities": state.get("capabilities", []),
            },
            reason,
        )
    except (QueueError, OSError, sqlite3.Error, ValueError, KeyError):
        return OperatorObservation(
            owner,
            utc_now(),
            None,
            "unknown",
            "unavailable",
            {},
            "owner_evidence_unavailable",
        )


def probe_upgrade_compatibility(
    root: str | Path, *, required_capabilities: tuple[str, ...] = ()
) -> OperatorObservation:
    """Read storage compatibility in the candidate runtime without migration.

    Migration is forward-only and offline. Workload profile qualification is a
    separate owner and is never inferred from compatible service storage.
    """
    from .local_daemon import _COORDINATOR_SCHEMA_VERSION, _AGENT_SCHEMA_VERSION
    from ._maintenance import MAINTENANCE_CAPABILITY
    from .errors import QueueError

    owner = None
    try:
        with _readonly_root(Path(root)) as conn:
            metadata = dict(conn.execute("SELECT key,value FROM root_metadata"))
            current = conn.execute("PRAGMA user_version").fetchone()[0]
        owner = metadata.get("stable_id")
        role = metadata.get("role")
        if role not in {"coordinator", "local-agent"}:
            raise ValueError("unsupported native role")
        target = (
            _COORDINATOR_SCHEMA_VERSION
            if role == "coordinator"
            else _AGENT_SCHEMA_VERSION
        )
        supported = current == target or (
            role == "coordinator" and current in {12, 15, 16, 17, 18}
        )
        missing = sorted(
            set(required_capabilities) - {OPERATOR_CAPABILITY, "daemon-control-v1", MAINTENANCE_CAPABILITY, CONDITIONAL_CONTROL_CAPABILITY, "quiescent-profile-promotion-v1"}
        )
        reason = (
            "unsupported_capability"
            if missing
            else None
            if supported
            else "unsupported_storage_version"
        )
        return OperatorObservation(
            owner,
            utc_now(),
            str(current),
            "current",
            "available",
            {
                "current_storage_version": current,
                "target_storage_version": target,
                "migration_direction": "none"
                if current == target
                else "forward"
                if supported
                else "unsupported",
                "offline_required": current != target,
                "compatible": supported and not missing,
                "protocol_version": "1",
                "capabilities": ["daemon-control-v1", OPERATOR_CAPABILITY, MAINTENANCE_CAPABILITY, CONDITIONAL_CONTROL_CAPABILITY, "quiescent-profile-promotion-v1"],
                "missing_capabilities": cast(list[PlainData], missing),
                "profile_constraints": "unchanged_bindings_require_separate_qualification",
            },
            reason,
        )
    except (QueueError, OSError, sqlite3.Error, ValueError):
        return OperatorObservation(
            owner,
            utc_now(),
            None,
            "unknown",
            "unavailable",
            {},
            "storage_evidence_unavailable",
        )


def _assignment_observation(
    daemon: LocalDaemon, assignment_id: str
) -> OperatorObservation:
    """Join one coordinator assignment without exporting receipts or host paths."""
    from .errors import QueueServiceError

    with sqlite3.connect(
        f"{daemon.config.execution_database.resolve().as_uri()}?mode=ro", uri=True
    ) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT agent_id, session_id, claim_id, state FROM coordinator_assignments WHERE assignment_id = ?",
            (assignment_id,),
        ).fetchone()
    if row is None:
        raise QueueServiceError("managed assignment was not found")
    with daemon._connection() as conn:
        remote = conn.execute(
            "SELECT state, start_permitted, report_digest, report_json, run_uri, stage_name, attempt, profile_json, provider_release_proof_json FROM remote_assignments WHERE assignment_id = ?",
            (assignment_id,),
        ).fetchone()
        control = conn.execute(
            "SELECT state, result_code, acknowledged FROM remote_assignment_controls WHERE assignment_id = ?",
            (assignment_id,),
        ).fetchone()
    proof = (
        None
        if remote is None or remote["provider_release_proof_json"] is None
        else json.loads(remote["provider_release_proof_json"])
    )
    if proof is not None:
        proof.pop("retirement_secret", None)
    report = None if remote is None or remote["report_json"] is None else json.loads(remote["report_json"])
    claim = None if report is None else (report.get("executor_metadata") or {}).get("native_claim_observation")
    return OperatorObservation(
        daemon._require_started(),
        daemon._clock(),
        None,
        "current",
        "available",
        {
            "assignment_id": assignment_id,
            "agent_id": row["agent_id"],
            "session_id": row["session_id"],
            "claim_id": row["claim_id"],
            "coordinator_state": row["state"],
            "remote_state": None if remote is None else remote["state"],
            "terminal_acknowledged": remote is not None
            and remote["report_digest"] is not None,
            "release_proof": proof,
            "released": row["state"] == "released",
            "containment": None
            if control is None
            else {
                "state": control["state"],
                "code": control["result_code"],
                "acknowledged": bool(control["acknowledged"]),
            },
            "run_uri": None if remote is None else remote["run_uri"],
            "stage_name": None if remote is None else remote["stage_name"],
            "attempt": None if remote is None else remote["attempt"],
            "profile": None if remote is None else json.loads(remote["profile_json"]),
            "actual_claims": ({"availability": "available", **claim} if claim is not None else {
                "availability": "unavailable", "reason": "agent_local_evidence_required",
            }),
        },
    )


def inspect_local_assignment(
    root: str | Path, assignment_id: str
) -> OperatorObservation:
    """Read one host-local claim and its exact retained launch GPU bindings.

    UUIDs come only from the immutable launch environment of a started native
    supervisor launch. Pending/unknown launches expose unavailable device proof;
    requested resources are never substituted for actual bindings. Terminal
    acknowledgement, containment and provider release remain separate facts.
    """
    from .errors import QueueError

    root = Path(root)
    owner = None
    try:
        with _readonly_root(root) as conn:
            owner = dict(conn.execute("SELECT key,value FROM root_metadata")).get(
                "stable_id"
            )
        with sqlite3.connect(
            f"{(root / 'journal.sqlite').resolve().as_uri()}?mode=ro", uri=True
        ) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT identity_json, state, process_execution_id, result_json FROM assignments WHERE assignment_id = ?",
                (assignment_id,),
            ).fetchone()
        if row is None:
            return OperatorObservation(
                owner,
                utc_now(),
                None,
                "unknown",
                "unavailable",
                {"assignment_id": assignment_id},
                "assignment_not_found",
            )
        identity = json.loads(row["identity_json"])
        with sqlite3.connect(
            f"{(root / 'supervisor' / 'supervisor.sqlite').resolve().as_uri()}?mode=ro",
            uri=True,
        ) as conn:
            conn.row_factory = sqlite3.Row
            launch = conn.execute(
                "SELECT launch_json, state, revision, pid FROM launches WHERE json_extract(launch_json, '$.assignment_id') = ? LIMIT 1",
                (assignment_id,),
            ).fetchone()
        raw = None if launch is None else json.loads(launch["launch_json"])
        binding = (
            None
            if raw is None
            or launch is None
            or launch["pid"] is None
            or launch["state"] not in {"running", "exited", "contained"}
            else raw["environment"].get("CUDA_VISIBLE_DEVICES")
        )
        uuids = (
            None if binding is None else [item for item in binding.split(",") if item]
        )
        if uuids is not None and not all(item.startswith("GPU-") for item in uuids):
            uuids = None
        return OperatorObservation(
            owner,
            utc_now(),
            None if launch is None else str(launch["revision"]),
            "retained",
            "available",
            {
                "assignment_id": assignment_id,
                "session_id": identity["session_id"],
                "claim_id": identity["claim_id"],
                "state": row["state"],
                "actual_gpu_uuids": uuids,
                "device_proof_reason": None
                if uuids is not None
                else "actual_uuid_binding_unavailable",
                "terminal_acknowledged": row["state"]
                in {"terminal_acknowledged", "providers_released", "released"},
                "providers_released": row["state"]
                in {"providers_released", "released"},
                "containment": None if launch is None else launch["state"],
                "continuity_epoch": None if raw is None else raw["continuity_epoch"],
            },
        )
    except (QueueError, OSError, sqlite3.Error, ValueError, KeyError):
        return OperatorObservation(
            owner,
            utc_now(),
            None,
            "unknown",
            "unavailable",
            {"assignment_id": assignment_id},
            "assignment_evidence_unavailable",
        )


def control_intent_digest(intent: Mapping[str, PlainData]) -> str:
    """Digest the exact native agent-control intent using its retained encoding."""
    import hashlib

    return hashlib.sha256(
        json.dumps(intent, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = [
    "OPERATOR_CAPABILITY",
    "OperatorObservation",
    "inspect_native_service",
    "inspect_local_assignment",
    "probe_upgrade_compatibility",
    "control_intent_digest",
]
