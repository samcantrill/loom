"""Text views of the scheduling and execution evidence returned by the coordinator."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ._terminal import age, cell, fields, page_text, table


_MAINTENANCE_WAITS = {
    "accepted_work_or_preparation": "Accepted work or preparation to finish",
    "assignment_publication_or_claim_release": "Assignment publication or claim release",
    "agent_control_settlement": "Agent controls to settle",
    "coordinator_reconciliation_unavailable": "Coordinator reconciliation to become available",
}


def _maintenance(payload: Mapping[str, Any]) -> str:
    if "gate" in payload:
        return (
            f"Operation {cell(payload['operation_id'])}\n"
            f"Mutation outcome: {cell(payload['mutation_outcome'])}\n"
            f"Admission after operation: {cell(payload['gate']['state'])}"
        )
    lines = [
        table(
            ("ADMISSION", "SETTLED", "MAINTENANCE ID"),
            [(payload["state"], payload["settled"], payload["maintenance_id"])],
            continuation_column=2,
            empty="",
        )
    ]
    if payload["wait_reasons"]:
        lines.extend(("", "Waiting for:"))
        for reason in payload["wait_reasons"]:
            lines.append(f"  • {cell(_MAINTENANCE_WAITS.get(reason, reason))}")
    return "\n".join(lines)


def _admissions(page: Mapping[str, Any], *, history: bool, wide: bool) -> str:
    headers = ["STATE", "AGE"]
    if not history:
        headers.append("PRINCIPAL")
    headers.extend(("QUEUE ITEM", "REASON"))
    if history or wide:
        headers.append("ADMISSION ID")
    if wide:
        headers.append("ACCEPTED AT")
    rows = []
    for admission in page["admissions"]:
        row = [admission["state"], age(admission["accepted_at"], page.get("as_of"))]
        if not history:
            row.append(admission["admitted_by"] or "unknown")
        row.extend((admission["queue_item_id"], admission.get("blocked_reason")))
        if history or wide:
            row.append(admission["admission_id"])
        if wide:
            row.append(admission["accepted_at"])
        rows.append(row)
    return page_text(
        table(
            headers,
            rows,
            wide=wide,
            priority_columns=(0, 1),
            continuation_column=headers.index("REASON"),
            empty="No matching admissions.",
        ),
        page,
    )


def _capacity(resource: Mapping[str, Any]) -> str:
    if resource["available"]:
        return "available"
    if resource["reason_code"] in {"loom_claimed", "external_process_detected"}:
        return "occupied"
    if resource["reason_code"] in {
        "observation_stale",
        "observation_unavailable",
        "device_missing",
    }:
        return "unknown"
    return "unavailable"


def _current_capacity(agent: Mapping[str, Any]) -> Mapping[str, Any]:
    if not agent["available"]:
        return {}
    if "offered_capacity" in agent:
        return agent["offered_capacity"]
    # Operator observations retain the full offer, including unmonitored GPU atoms.
    offer = agent.get("offer")
    if offer and offer["freshness"] == "current":
        return {
            "cpu": offer["cpu"],
            "gpu_devices_offered": len(offer["gpu_atoms"]) if offer["gpu_devices"] else None,
            "observed_at": offer["observed_at"],
        }
    return {}


def _resource_summary(agent: Mapping[str, Any], kind: str, offered: int | None) -> str:
    resources = [
        row for row in agent["resource_status"] if row["resource_kind"] == kind
    ]
    if resources:
        return ", ".join(dict.fromkeys(_capacity(row) for row in resources))
    if offered is not None:
        return "available" if offered > 0 else "unavailable"
    return "unknown"


def _agents(agents: Sequence[Mapping[str, Any]], *, wide: bool) -> str:
    rows = []
    for agent in agents:
        capacity = _current_capacity(agent)
        # The normal projection exposes a session state and a current capacity offer.
        # Only operator observations carry a separate connectivity fact.
        session = agent["state"]
        if "connected" in agent:
            session = "connected" if agent["connected"] else "disconnected"
        row = [
            agent["agent_id"],
            session,
            agent["available"],
            _resource_summary(agent, "cpu", capacity.get("cpu")),
            _resource_summary(agent, "gpu", capacity.get("gpu_devices_offered")),
            ", ".join(agent["pools"]) or None,
        ]
        timestamps = [
            r["observed_at"] for r in agent["resource_status"] if r["observed_at"]
        ]
        if capacity.get("observed_at"):
            timestamps.append(capacity["observed_at"])
        row.append(age(min(timestamps)) if timestamps else None)
        rows.append(row)
    headers = ["AGENT", "SESSION", "AVAILABLE", "CPU CAPACITY", "GPU CAPACITY", "POOLS"]
    if any(row[-1] is not None for row in rows):
        headers.append("OBS AGE")
    else:
        rows = [row[:-1] for row in rows]
    return table(headers, rows, wide=wide, empty="No matching agents.")


def _resources(resources: Sequence[Mapping[str, Any]], as_of: str | None) -> str:
    rows = [
        (
            r["resource_kind"],
            r["local_capacity_key"],
            _capacity(r),
            r["reason_code"],
            age(r["observed_at"], as_of),
        )
        for r in resources
    ]
    return table(
        ("RESOURCE", "CAPACITY KEY", "CAPACITY", "REASON", "OBS AGE"),
        rows,
        continuation_column=3,
        empty="Resource observations unavailable.",
    )


def _status(payload: Mapping[str, Any]) -> str:
    status = payload.get("value", payload)
    if not status:
        return "\n".join(
            fields(payload, ("availability", "reason", "owner", "observed_at"))
        )
    scheduling = "ready" if status["scheduling_ready"] else "unready"
    row = (
        status["coordinator_id"],
        status["service_health"],
        scheduling,
        status["active_admissions"],
        status["waiting_admissions"],
        status["running_assignments"],
    )
    lines = [
        table(
            (
                "COORDINATOR",
                "HEALTH",
                "SCHEDULING",
                "ACTIVE",
                "WAITING",
                "RUNNING ASSIGNMENTS",
            ),
            [row],
            empty="",
        ),
        f"Observed: {cell(status['as_of'])} ({age(status['as_of'])} ago)",
    ]
    if status.get("service_diagnostic"):
        lines.append("Service diagnostic: " + cell(status["service_diagnostic"]))
    if status.get("local_resource_status"):
        lines.append(_resources(status["local_resource_status"], status["as_of"]))
    return "\n".join(lines)


def _agent(payload: Mapping[str, Any]) -> str:
    agent = payload.get("value", payload)
    if not agent:
        return "\n".join(
            fields(payload, ("availability", "reason", "owner", "observed_at"))
        )
    lines = [_agents([agent], wide=True)]
    lines.extend(
        fields(
            agent,
            (
                "session_id",
                "state",
                "offer_freshness",
                "drained",
                "config_revision",
                "inventory_revision",
                "availability_revision",
                "coordinator_epoch",
                "capabilities",
                "control",
            ),
        )
    )
    lines.append(_resources(agent["resource_status"], payload.get("observed_at")))
    if agent.get("offered_capacity"):
        lines.append("Current capacity offer:")
        lines.extend(fields(agent["offered_capacity"], ("cpu", "gpu_devices_offered", "observed_at"), indent="  "))
    if agent.get("offer"):
        lines.append("Capacity offer:")
        lines.extend(
            fields(
                agent["offer"],
                ("freshness", "observed_at", "cpu", "memory_bytes", "gpu_devices", "gpu_atoms"),
                indent="  ",
            )
        )
    if payload.get("observed_at"):
        lines.append(
            f"Observed: {cell(payload['observed_at'])} ({age(payload['observed_at'])} ago)"
        )
    return "\n".join(lines)


def _admission(payload: Mapping[str, Any]) -> str:
    admission = payload.get("admission", {})
    lines = [
        f"Admission {cell(admission.get('admission_id'))}: {cell(admission.get('state'))}"
    ]
    lines.extend(
        fields(
            admission,
            (
                "blocked_reason",
                "queue_item_id",
                "accepted_at",
                "run_uri",
                "execution_owner",
                "authority_operation_id",
                "cancellation_operation_id",
            ),
        )
    )
    owners = payload.get("owners", {})
    # The authority also appears inside owners. Render its current stages once.
    authority = payload.get("authority") or owners.get("authority", {})
    lines.append("Run authority:")
    lines.extend(
        fields(
            authority,
            ("state", "availability", "diagnostic", "stages", "stage_reasons"),
            indent="  ",
        )
    )
    for name, keys in (
        ("scheduling", ("state", "diagnostic", "work")),
        ("assignment", ("state", "diagnostic", "assignments")),
        ("slurm", ("state", "diagnostic", "assignments")),
        ("execution", ("state", "diagnostic", "journal")),
        ("run_result", ("state", "availability", "diagnostic")),
        ("cancellation", ("state", "operation_id", "effective", "settling")),
    ):
        if name in owners:
            lines.append(name.replace("_", " ").capitalize() + ":")
            lines.extend(fields(owners[name], keys, indent="  "))
    lines.extend(
        fields(
            owners,
            ("scheduling_waits", "agent_sessions", "input_validation", "slurm_storage"),
        )
    )
    return "\n".join(lines)


def format_queue_text(command: str, payload: Mapping[str, Any], *, wide: bool) -> str:
    if command in {"list", "daemon-admissions"}:
        return _admissions(payload, history=command == "daemon-admissions", wide=wide)
    if command == "daemon-maintenance":
        return _maintenance(payload)
    if command == "daemon-status":
        return _status(payload)
    if command == "daemon-agents":
        return page_text(_agents(payload["agents"], wide=wide), payload)
    if command == "daemon-agent":
        return _agent(payload)
    if command == "daemon-admission":
        return _admission(payload)
    if command in {"daemon-assignment", "agent-assignment"}:
        data = payload["value"]
        lead = (
            data.get("coordinator_state")
            or data.get("state")
            or payload["availability"]
        )
        lines = [f"Assignment {cell(data.get('assignment_id'))}: {cell(lead)}"]
        lines.extend(fields(payload, ("reason", "freshness", "observed_at")))
        lines.extend(
            fields(
                data,
                tuple(
                    k for k in data if k not in {"assignment_id", "coordinator_state"}
                ),
            )
        )
        return "\n".join(lines)
    if command == "daemon-wait":
        from loom.timestamps import utc_timestamp

        return f"{utc_timestamp()}  {cell(payload['state'])}  {cell(payload['queue_item_id'])}  {cell(payload['admission_id'])}"
    if command == "daemon-operation-wait":
        return f"{cell(payload['kind'])}\n" + format_queue_text(
            "daemon-operation", payload["operation"], wide=wide
        )
    if "operation_id" in payload and "state" in payload:
        lines = [f"Operation {cell(payload['operation_id'])}: {cell(payload['state'])}"]
        lines.extend(
            fields(
                payload, ("code", "reason", "kind", "acknowledged", "mutation_outcome")
            )
        )
        if command == "daemon-operation":
            lines.extend(fields(payload, ("condition", "result")))
        elif isinstance(payload.get("result"), Mapping):
            result = payload["result"]
            lines.extend(
                fields(
                    result,
                    ("code", "reason", "run_uri", "queue_item_id", "admission_id"),
                )
            )
            for key in ("admission", "prepared_run", "binding"):
                if isinstance(result.get(key), Mapping):
                    lines.extend(
                        fields(
                            result[key], ("run_uri", "queue_item_id", "admission_id")
                        )
                    )
        return "\n".join(lines)
    # Role checks and init/management receipts use different native result shapes.
    return "\n".join([command, *fields(payload, tuple(payload))])
