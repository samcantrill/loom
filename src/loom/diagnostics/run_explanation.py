"""Pure explanations of independently observed native run facts.

No lifecycle, admission, recovery, or log access occurs here. Missing times and
revisions stay missing; freshness is never promoted by rendering an old fact.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from collections.abc import Mapping
from typing import TYPE_CHECKING
import shlex

from loom.serialization import PlainData
from .run_inspection import (
    RunInspectionAxis,
    RunInspectionAxisName,
    RunInspectionFailure,
    RunInspectionResponse,
    MAX_INSPECTION_RECORDS,
    _owner_axis,
    _empty_axes,
)

if TYPE_CHECKING:
    from loom.coordinator import RunObservation
    from loom.queue.local_daemon import LocalDaemonAdmissionDetail


@dataclass(frozen=True, slots=True)
class RunExplanation:
    """Read-only reasons with their native evidence and optional operation ID.

    ``summary`` is logical lifecycle when available, never aggregate health.
    ``facts`` retain independent owner revision/time/freshness; ``reasons`` are
    presentation families, and each retains the authoritative native code.
    """

    reference: str
    summary: str
    facts: tuple[RunInspectionAxis, ...]
    reasons: tuple[tuple[str, RunInspectionAxis], ...]
    next_actions: tuple[str, ...]
    inspection: RunInspectionResponse | None = None

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "reference": self.reference,
            "summary": self.summary,
            "facts": [fact.to_dict() for fact in self.facts],
            "reasons": [
                {"family": family, "evidence": fact.to_dict()}
                for family, fact in self.reasons
            ],
            "next_actions": list(self.next_actions),
            "inspection": None
            if self.inspection is None
            else self.inspection.to_dict(),
        }

    def format_text(self) -> str:
        lines = [f"{self.reference}: {self.summary}"]
        if self.inspection is not None and not isinstance(
            self.inspection, RunInspectionFailure
        ):
            if self.inspection.admission_id is not None:
                lines.append(f"  admission: {self.inspection.admission_id}")
            if self.inspection.queue_item_id is not None:
                lines.append(f"  queue item: {self.inspection.queue_item_id}")
            for item in self.inspection.truncation:
                if item.returned_count < item.total_count:
                    lines.append(
                        f"  {item.collection}: {item.returned_count}/{item.total_count} facts returned"
                    )
        for fact in self.facts:
            lines.append(
                f"  {fact.name.value}: {fact.state} ({fact.owner}; revision {fact.revision}; "
                f"observed_at {fact.observed_at}; {fact.freshness}; {fact.availability})"
                + (f" [{fact.code}]" if fact.code else "")
            )
        lines.extend(
            f"  reason: {family.replace('_', ' ')} [{fact.code or fact.state}]"
            for family, fact in self.reasons
        )
        lines.extend(f"  next: {action}" for action in self.next_actions)
        return "\n".join(lines)


def explain_run(
    inspection: RunInspectionResponse | None,
    *,
    observation: RunObservation | None = None,
    detail: LocalDaemonAdmissionDetail | None = None,
    operation_id: str | None = None,
    deployment: str | None = None,
    error_code: str | None = None,
) -> RunExplanation:
    """Derive one explanation from retained facts, without reading or mutating.

    ``error_code`` is a native response retained by the caller (for example a
    maintenance refusal), never inferred from the current admission gate.
    Deployment is only used to quote a connect-only suggested command.
    """
    facts: list[RunInspectionAxis] = []
    summary = "unavailable"
    reference = operation_id or "run"
    if inspection is not None and not isinstance(inspection, RunInspectionFailure):
        reference = operation_id or inspection.run_uri
        facts.extend(inspection.axes)
        lifecycle = next(
            axis
            for axis in inspection.axes
            if axis.name is RunInspectionAxisName.LIFECYCLE
        )
        summary = (
            lifecycle.state if lifecycle.availability == "available" else "unavailable"
        )
    elif isinstance(inspection, RunInspectionFailure):
        error_code = error_code or inspection.code.value
    detail = detail or (None if observation is None else observation.detail)
    if detail is not None:
        facts.extend(_detail_facts(detail, include_axes=not facts))
        if (
            summary == "unavailable"
            and detail.authority.get("availability") == "available"
        ):
            summary = str(detail.authority["state"])
    if observation is not None:
        reference = observation.operation_id
        if observation.admission is not None and summary == "unavailable":
            admission = observation.admission
            summary = admission.state.value
            facts.append(
                RunInspectionAxis(
                    RunInspectionAxisName.ADMISSION,
                    "coordinator",
                    "available",
                    summary,
                    admission.revision,
                    admission.accepted_at,
                    "current",
                    None,
                )
            )
        operation = observation.operation
        if operation is not None and observation.admission is None:
            summary = operation.state
            facts.append(
                RunInspectionAxis(
                    RunInspectionAxisName.ADMISSION,
                    "coordinator-preparation",
                    "available",
                    operation.state,
                    None,
                    None,
                    "unknown",
                    operation.code,
                )
            )
    if error_code is not None:
        facts.append(
            RunInspectionAxis(
                RunInspectionAxisName.SERVICE_HEALTH,
                "coordinator",
                "unavailable",
                error_code,
                None,
                None,
                "unavailable",
                error_code,
            )
        )
        if summary == "unavailable":
            summary = error_code
    facts = list(dict.fromkeys(facts))
    if len(facts) > MAX_INSPECTION_RECORDS:
        facts = facts[: MAX_INSPECTION_RECORDS - 1] + [
            RunInspectionAxis(
                RunInspectionAxisName.SERVICE_HEALTH,
                "explanation",
                "unavailable",
                "truncated",
                None,
                None,
                "unknown",
                "evidence_truncated",
            )
        ]
    reasons: list[tuple[str, RunInspectionAxis]] = []
    for fact in facts:
        family = _family(fact)
        if family is not None and (family, fact) not in reasons:
            reasons.append((family, fact))
    actions: list[str] = []
    if operation_id is not None and deployment is not None:
        actions.append(
            shlex.join(
                [
                    "loom",
                    "runs",
                    "follow",
                    "--operation-id",
                    operation_id,
                    "--deployment",
                    deployment,
                ]
            )
        )
    elif inspection is not None and not isinstance(inspection, RunInspectionFailure):
        actions.append(
            "Observe the same run through its selected inspection connection."
        )
    families = {family for family, _ in reasons}
    if "owner_unavailable" in families:
        actions.append(
            "Restore the owner connection and observe the original identity; do not submit a replacement."
        )
    if "waiting_for_resources" in families:
        actions.append("Wait for compatible capacity.")
    if "incompatible_profile" in families:
        actions.append(
            "Inspect the accepted execution profile and workload requirements."
        )
    if "cancellation_awaiting_containment" in families or "cleanup_pending" in families:
        actions.append(
            "Observe containment and resource release separately from the logical result."
        )
    if "maintenance_refusal" in families:
        actions.append(
            "Ask the operator to inspect maintenance; no admission is established by this refusal."
        )
    return RunExplanation(
        reference, summary, tuple(facts), tuple(reasons), tuple(actions), inspection
    )


def _detail_facts(
    detail: LocalDaemonAdmissionDetail, *, include_axes: bool
) -> list[RunInspectionAxis]:
    """Project already-authorized owner detail without copying private payloads."""
    axes = _empty_axes()
    admission = detail.admission
    axes[RunInspectionAxisName.ADMISSION] = RunInspectionAxis(
        RunInspectionAxisName.ADMISSION,
        "coordinator",
        "available",
        admission.state.value,
        admission.revision,
        admission.accepted_at,
        "current",
        None,
    )
    axes[RunInspectionAxisName.LIFECYCLE] = _owner_axis(
        RunInspectionAxisName.LIFECYCLE, detail.authority
    )
    facts: list[RunInspectionAxis] = []
    for key, name in (
        ("scheduling", RunInspectionAxisName.SCHEDULING),
        ("assignment", RunInspectionAxisName.ASSIGNMENT),
        ("slurm", RunInspectionAxisName.EXTERNAL_SCHEDULER),
        ("execution", RunInspectionAxisName.TRANSFER_RESULT),
        ("cancellation", RunInspectionAxisName.CANCELLATION),
        ("service", RunInspectionAxisName.SERVICE_HEALTH),
    ):
        owner = detail.owners.get(key)
        if not isinstance(owner, Mapping):
            continue
        axis = _owner_axis(name, owner)
        axes[name] = axis
        for collection in ("work", "assignments", "journal"):
            rows = owner.get(collection)
            if not isinstance(rows, (list, tuple)):
                continue
            for row in rows:
                if not isinstance(row, Mapping) or not isinstance(
                    row.get("state"), str
                ):
                    continue
                code = row.get("diagnostic") or row.get("decline_reason_code")
                fact = replace(
                    axis,
                    state=str(row["state"]),
                    code=code if isinstance(code, str) else None,
                )
                if fact not in facts:
                    facts.append(fact)
    sessions = detail.owners.get("agent_sessions", ())
    if isinstance(sessions, (list, tuple)):
        for session in sessions:
            if isinstance(session, Mapping):
                axis = _owner_axis(RunInspectionAxisName.ASSIGNMENT, session)
                code, freshness = session.get("diagnostic"), session.get("freshness")
                facts.append(
                    replace(
                        axis,
                        code=code if isinstance(code, str) else None,
                        freshness=freshness
                        if isinstance(freshness, str)
                        else "unknown",
                    )
                )
    if detail.owners.get("agent_sessions_truncated"):
        facts.append(
            RunInspectionAxis(
                RunInspectionAxisName.ASSIGNMENT,
                "agent-session",
                "unavailable",
                "truncated",
                None,
                None,
                "unknown",
                "agent_evidence_truncated",
            )
        )
    return [*axes.values(), *facts] if include_axes else facts


def _family(fact: RunInspectionAxis) -> str | None:
    state, code = fact.state.lower(), fact.code
    if code == "maintenance_in_progress":
        return "maintenance_refusal"
    if code == "incompatible_profile":
        return "incompatible_profile"
    if code == "agent_disconnected_or_drained":
        return "agent_disconnected_or_drained"
    if fact.owner == "coordinator-preparation":
        if code == "candidate_publication_failed":
            return "publication_failed"
        if state in {"pending", "applying"}:
            return "preparation_incomplete"
        if state in {"failed", "conflict"}:
            return "preparation_failed"
    if fact.availability == "unavailable":
        return (
            None
            if code in {"not_found", "unauthorized", "invalid_request"}
            else "owner_unavailable"
        )
    if fact.name is RunInspectionAxisName.SCHEDULING and state == "ready":
        return "waiting_for_resources"
    if state in {
        "prepare_unknown",
        "activation_unknown",
        "start_unknown",
        "unknown",
    } and fact.name in {
        RunInspectionAxisName.ASSIGNMENT,
        RunInspectionAxisName.TRANSFER_RESULT,
        RunInspectionAxisName.EXTERNAL_SCHEDULER,
    }:
        return "unknown_process_ownership"
    if fact.name is RunInspectionAxisName.TRANSFER_RESULT and state == "result_durable":
        return "publication_pending"
    if fact.name in {
        RunInspectionAxisName.ASSIGNMENT,
        RunInspectionAxisName.EXTERNAL_SCHEDULER,
    } and state in {"terminal", "logical_released"}:
        return "cleanup_pending"
    if fact.name is RunInspectionAxisName.TRANSFER_RESULT and state in {
        "terminal_acknowledged",
        "providers_released",
    }:
        return "cleanup_pending"
    if fact.name is RunInspectionAxisName.CANCELLATION and state in {
        "requested",
        "requested_degraded",
        "effective",
        "settling",
    }:
        return "cancellation_awaiting_containment"
    return None
