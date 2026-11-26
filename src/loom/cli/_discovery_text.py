"""Terminal presentations of native discovery pages, including evidence gaps."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from ._terminal import cell, fields, page_text, table


def _evidence(owners: Mapping[str, Any], name: str) -> str:
    axis = owners.get(name)
    if not axis or axis.get("availability") == "unavailable":
        return "unavailable"
    if name == "slurm":
        values = [
            row.get("submission", {}).get("scheduler_state") or "unknown"
            for row in axis.get("assignments", [])
        ]
    else:
        rows = axis.get("journal" if name == "execution" else "assignments", [])
        values = [row["state"] for row in rows]
    return ", ".join(dict.fromkeys(values)) or axis.get("state", "unknown")


def _search(command: str, page: Mapping[str, Any], wide: bool) -> str:
    headers = {
        "search": ("RUN", "LIFECYCLE", "PRINCIPAL", "CREATED AT"),
        "submissions": ("OPERATION ID", "PRINCIPAL", "ACCEPTED AT", "STATE"),
        "jobs": (
            "ADMISSION ID",
            "QUEUE ITEM",
            "STATE",
            "ASSIGNMENT",
            "LOCAL EXEC",
            "SLURM",
        ),
    }[command]
    rows = []
    details = []
    for item in page["items"]:
        identity = item["identity"]
        native = item.get("native", item.get("reference", {}))
        if command == "jobs":
            owners = item.get("sources", {}).get("job_associations", {})
            assignment = _evidence(owners, "assignment")
            execution = _evidence(owners, "execution")
            slurm = _evidence(owners, "slurm")
            if "fields" in item:
                assignment = execution = slurm = "not selected"
            rows.append(
                (
                    identity,
                    native.get("queue_item_id"),
                    native.get("state"),
                    assignment,
                    execution,
                    slurm,
                )
            )
        elif command == "submissions":
            rows.append(
                (
                    identity,
                    native.get("principal_id", "unknown"),
                    native.get("accepted_at"),
                    native.get("state"),
                )
            )
        else:
            rows.append(
                (
                    identity,
                    native.get("status", "unknown"),
                    native.get("principal_id", "unknown"),
                    native.get("created_at"),
                )
            )

        if item.get("diagnostic"):
            details.append(f"{cell(identity)}: {cell(item['diagnostic'])}")
        for projection in item.get("fields", []):
            field = projection["field"]
            path = ".".join([field["source"], *field["path"]])
            value = (
                cell(projection.get("value"))
                if projection["availability"] == "present"
                else projection["availability"]
            )
            details.append(f"{cell(identity)}  {cell(path)}: {value}")

    noun = "runs" if command == "search" else command
    incomplete = page.get("coverage", {}).get("complete") is False or bool(
        page.get("next_cursor")
    )
    empty = (
        f"No {noun} returned on this page." if incomplete else f"No matching {noun}."
    )
    content = table(headers, rows, wide=wide, empty=empty)
    return page_text("\n".join([content, *details]), page)


def _outputs(page: Mapping[str, Any], wide: bool) -> str:
    rows = []
    for item in page["items"]:
        locator = item.get("locator", {})
        artifact = item.get("artifact", {})
        rows.append(
            (
                item["outcome"],
                item["matched_run_uri"],
                item["matched_stage_name"],
                locator.get("output_name"),
                artifact.get("artifact_type"),
                artifact.get("artifact_id"),
                item.get("availability"),
            )
        )
    return page_text(
        table(
            (
                "OUTCOME",
                "MATCHED RUN",
                "STAGE",
                "OUTPUT",
                "TYPE",
                "ARTIFACT ID",
                "AVAILABILITY",
            ),
            rows,
            wide=wide,
            empty="No outputs returned on this page.",
        ),
        page,
    )


def _lineage_name(identity: Mapping[str, Any]) -> str:
    if "external_input" in identity:
        return f"external input {cell(identity['external_input'])} for {_lineage_name(identity['consumer'])}"
    return " / ".join(
        cell(identity[key])
        for key in ("run_uri", "stage_name", "attempt_id", "commit_id", "output_name")
        if key in identity
    )


def _lineage(page: Mapping[str, Any]) -> str:
    # A page can contain an edge without either node. Retain both endpoints.
    children: dict[str, list[tuple[str, str]]] = defaultdict(list)
    labels: dict[str, str] = {}
    targets = set()

    def key(identity: Mapping[str, Any]) -> str:
        # Group by the exact locator; rendered path separators may occur inside names.
        exact = cell(identity)
        labels.setdefault(exact, _lineage_name(identity))
        return exact

    for item in page["items"]:
        if item["kind"] == "edge":
            source, target = key(item["source"]), key(item["target"])
            children[source].append((item["relation"], target))
            targets.add(target)
        else:
            node = key(item["identity"])
            suffix = ", selected" if item.get("selected") else ""
            labels[node] = (
                f"{_lineage_name(item['identity'])} ({item['entity']}{suffix})"
            )
    lines: list[str] = []
    seen: set[str] = set()

    def subtree(name: str, prefix: str) -> None:
        if name in seen:
            return
        seen.add(name)
        for relation, target in children[name]:
            lines.append(f"{prefix}└─ {cell(relation)} → {labels[target]}")
            subtree(target, prefix + "   ")

    for name in [*(k for k in labels if k not in targets), *labels]:
        if name not in seen:
            lines.append(labels[name])
            subtree(name, "  ")
    return page_text(
        "\n".join(lines) or "No lineage records on this page.",
        page,
        cursor_option="the same --query and its cursor set to",
    )


def format_discovery_text(command: str, page: Mapping[str, Any], *, wide: bool) -> str:
    if command in {"jobs", "submissions", "search"}:
        return _search(command, page, wide)
    if command == "outputs":
        return _outputs(page, wide)
    if command == "lineage":
        return _lineage(page)
    return "\n".join([command, *fields(page, tuple(page))])
