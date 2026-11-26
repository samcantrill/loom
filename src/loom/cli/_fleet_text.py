"""Terminal summaries of the evidence returned by Fleet observation commands."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._terminal import age, cell, fields, table


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
        issues.append(
            f"Profile {cell(profile['profile_id'])}: {cell(profile['reason'])}"
        )
    return issues


def format_fleet_status(report: Mapping[str, Any], *, explain: bool) -> str:
    rows = []
    details = []
    for name, host in report["hosts"].items():
        native = host["native"]
        coordinator = name == "coordinator"
        rows.append(
            (
                name,
                "coordinator" if coordinator else "agent",
                native["value"].get(
                    "service_health" if coordinator else "state", "unknown"
                ),
                native["freshness"],
                age(native["observed_at"]),
                native.get("reason"),
            )
        )
        notes = _host_issues(host)
        if explain:
            notes.append(f"SSH alias: {cell(host['host'])}")
            for kind in (
                "native",
                "service_manager",
                "native_owner",
                "installation",
                "storage",
                "declaration",
                "identity_binding",
            ):
                if kind in host:
                    fact = host[kind]
                    reason = (
                        f"  reason={cell(fact['reason'])}" if fact.get("reason") else ""
                    )
                    notes.append(f"{kind.replace('_', ' ')}: {_evidence(fact)}{reason}")
        details.append(notes)

    heading = (
        f"Fleet {cell(report['fleet'])}    Qualification: {cell(report['outcome'])}"
    )
    body = table(
        ("HOST", "ROLE", "HEALTH / SESSION", "EVIDENCE", "OBS AGE", "REASON"),
        rows,
        priority_columns=(0, 2),
        continuation_column=5,
        row_details=details,
        empty="No hosts selected.",
    )
    lines = [heading, body]
    if "coordinator" not in report["hosts"]:
        coordinator = report["coordinator"]
        summary = coordinator.get("reason") or coordinator["value"].get(
            "service_health", "unknown"
        )
        lines.append(f"Coordinator: {cell(summary)}")
        if explain:
            lines.append(_evidence(coordinator))
    return "\n".join(lines)


def _check(kind: str, fact: Mapping[str, Any]) -> tuple[str, str]:
    """Use each check's own assertion when naming its result."""
    if kind == "runtime release":
        if fact["outcome"] == "passed":
            return (
                "verified",
                f"Local bundle hashes validated for {cell(fact['release_id'])}",
            )
        return fact["outcome"], fact["reason"]
    if kind == "profile":
        if fact["supported_declaration"]:
            return (
                "declared",
                f"{cell(fact['profile_id'])} ({cell(fact['execution_kind'])})",
            )
        return "failed", f"{cell(fact['profile_id'])}: {cell(fact['reason'])}"
    if fact["availability"] == "unavailable":
        # The Fleet producer marks a failed role-declaration check in the report outcome.
        return ("failed" if kind == "declaration" else "unavailable"), fact["reason"]
    if fact["freshness"] == "retained":
        return "retained", fact.get("reason") or "Retained observation"
    verified = {
        "declaration": "Protected role declaration validated",
        "credential_files": "Local credential file permissions validated",
        "identity_binding": "Certificate matched the declared agent",
    }
    if kind in verified:
        return "verified", verified[kind]
    value = fact["value"]
    return "observed", value.get("service_health") or value.get("state") or fact[
        "freshness"
    ]


def format_fleet_preflight(report: Mapping[str, Any], *, explain: bool) -> str:
    checks = [("fleet", "runtime release", report["release"])]
    if "coordinator" not in report["hosts"]:
        checks.append(("coordinator", "native", report["coordinator"]))
    for name, host in report["hosts"].items():
        for kind in (
            "declaration",
            "profile",
            "credential_files",
            "identity_binding",
            "native",
            "service_manager",
            "native_owner",
            "installation",
            "storage",
        ):
            if kind in host:
                checks.append((name, kind, host[kind]))

    entries = []
    for name, kind, fact in checks:
        result, detail = _check(kind, fact)
        notes = []
        if explain:
            if kind == "runtime release":
                notes = fields(
                    fact,
                    (
                        "scope",
                        "descriptor_sha256",
                        "requirements_sha256",
                        "manifest_sha256",
                        "wheel_count",
                    ),
                )
            elif kind == "profile":
                notes = fields(
                    fact, ("execution_kind", "supported_declaration", "qualified")
                )
            else:
                notes = [_evidence(fact)]
        entries.append(((name, kind.replace("_", " "), result, detail), notes))
    rank = {"failed": 0, "unavailable": 1, "retained": 2}
    entries.sort(key=lambda entry: rank.get(entry[0][2], 3))
    heading = f"Fleet {cell(report['fleet'])}    Preflight: {cell(report['outcome'])}"
    body = table(
        ("SCOPE", "CHECK", "RESULT", "DETAIL"),
        [row for row, _ in entries],
        row_details=[notes for _, notes in entries],
        priority_columns=(2, 1),
        continuation_column=3,
        empty="No preflight checks.",
    )
    return f"{heading}\n{body}"


def format_fleet_plan(report: Mapping[str, Any], *, explain: bool) -> str:
    lines = [
        f"Fleet {cell(report['fleet'])}    Plan",
        f"Reservation: {cell(report['reservation'])}",
    ]
    if explain:
        lines.extend(fields(report, ("service_manager", "issuer", "release")))
    for name, host in report["hosts"].items():
        dependency = " (dependency)" if host["dependency"] else ""
        lines.extend(("", f"{cell(name)}{dependency}"))
        for issue in ("conflict", "unavailable"):
            if issue in host:
                lines.append(f"  {issue.capitalize()}: {cell(host[issue])}")
        for number, action in enumerate(host.get("actions", ()), start=1):
            lines.append(f"  {number}. {cell(action)}")
        if explain:
            lines.extend(
                fields(
                    host,
                    ("host", "declaration_fingerprint", "credential_binding"),
                    indent="  ",
                )
            )
            observed = host.get("observation", {})
            lines.extend(
                fields(
                    observed,
                    (
                        "root_exists",
                        "bound_root",
                        "service_manager",
                        "credentials_complete",
                        "local_storage",
                        "boot_start",
                    ),
                    indent="  ",
                )
            )
    return "\n".join(lines)
