"""Terminal summaries of the evidence returned by Fleet observation commands."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._terminal import age, cell, table


def _evidence(fact: Mapping[str, Any]) -> str:
    return "  ".join(
        f"{key}={cell(fact.get(key))}"
        for key in ("availability", "freshness", "owner", "revision", "observed_at")
    )


def _host_issues(host: Mapping[str, Any]) -> list[str]:
    issues = []
    declaration = host["declaration"]
    if declaration["availability"] == "unavailable":
        issues.append(f"Declaration: {cell(declaration['reason'])}")
    profile = host.get("profile")
    if profile and not profile["supported_declaration"]:
        issues.append(f"Profile {cell(profile['profile_id'])}: {cell(profile['reason'])}")
    return issues


def format_fleet_status(report: Mapping[str, Any], *, explain: bool) -> str:
    rows = []
    details = []
    for name, host in report["hosts"].items():
        native = host["native"]
        coordinator = name == "coordinator"
        rows.append((
            name, "coordinator" if coordinator else "agent",
            native["value"].get("service_health" if coordinator else "state", "unknown"),
            native["freshness"], age(native["observed_at"]), native.get("reason"),
        ))
        notes = _host_issues(host)
        if explain:
            notes.append(f"SSH alias: {cell(host['host'])}")
            for kind in ("native", "service_manager", "native_owner", "installation", "storage",
                         "declaration", "identity_binding"):
                if kind in host:
                    fact = host[kind]
                    reason = f"  reason={cell(fact['reason'])}" if fact.get("reason") else ""
                    notes.append(f"{kind.replace('_', ' ')}: {_evidence(fact)}{reason}")
        details.append(notes)

    heading = f"Fleet {cell(report['fleet'])}    Qualification: {cell(report['outcome'])}"
    body = table(
        ("HOST", "ROLE", "HEALTH / SESSION", "EVIDENCE", "OBS AGE", "REASON"),
        rows, priority_columns=(0, 2), continuation_column=5,
        row_details=details, empty="No hosts selected.",
    )
    lines = [heading, body]
    if "coordinator" not in report["hosts"]:
        coordinator = report["coordinator"]
        summary = coordinator.get("reason") or coordinator["value"].get("service_health", "unknown")
        lines.append(f"Coordinator: {cell(summary)}")
        if explain:
            lines.append(_evidence(coordinator))
    return "\n".join(lines)
