"""Native read-only settlement proof for an explicitly selected service root."""

from __future__ import annotations

import json
import fcntl
import os
from pathlib import Path
import sqlite3
import stat
from typing import cast
from loom.serialization import PlainData

from .operations import OperatorObservation, inspect_native_service, _readonly_root
from ._service_lifetime import _retained_coordinator_operations


def inspect_adoption_service(
    root: str | Path, *, expected_root_id: str
) -> OperatorObservation:
    """Observe an existing service for installation adoption, without mutation.

    Coordinator schema 18 and agent schema 12 predecessors may lack the boot
    field in their process receipt. A live predecessor requires both its exact
    recorded Linux process start identity and a kernel-reported exclusive flock
    on this native root's owner inode. A remembered PID alone is insufficient.
    The coordinator's migrated schema 19 may retain that same stopped receipt.
    A missing/reused process requires a positively unowned existing owner lock
    before it can be reported stopped. No record, lock or process is created.

    This bounded compatibility proof is separate from ordinary boot-qualified
    inspection. It does not prove resource settlement or authorize a signal;
    the mutating owner must recheck and use the native replacement guard.
    """
    root = Path(root)
    observed = inspect_native_service(root, expected_root_id=expected_root_id)
    if (
        observed.availability != "available"
        or observed.value.get("ownership") == "live"
    ):
        return observed
    if observed.reason == "service_stopped":
        return observed
    recorded_boot = observed.value.get("recorded_boot_id")
    if recorded_boot is not None and recorded_boot != observed.value.get("boot_id"):
        return observed

    def unavailable(reason: str) -> OperatorObservation:
        return OperatorObservation(
            observed.owner,
            observed.observed_at,
            observed.revision,
            "unknown",
            "unavailable",
            observed.value,
            reason,
        )

    try:
        with _readonly_root(root) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        if (observed.value.get("role"), version) not in {
            ("coordinator", 18),
            ("coordinator", 19),
            ("local-agent", 12),
        }:
            return unavailable("unsupported_adoption_predecessor")
        descriptor = os.open(root / "owner.lock", os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
            ):
                return unavailable("owner_lock_unavailable")
            pid = observed.value.get("expected_process")
            started = observed.revision

            def matching_process() -> bool:
                if type(pid) is not int:
                    return False
                try:
                    process = Path(f"/proc/{pid}")
                    fields = (process / "stat").read_text().rsplit(")", 1)[1].split()
                    return (
                        process.stat().st_uid == os.getuid()
                        and fields[0] != "Z"
                        and fields[19] == started
                    )
                except FileNotFoundError:
                    return False

            matches = matching_process()
            held = False
            for line in Path("/proc/locks").read_text().splitlines():
                fields = line.split()
                if len(fields) != 8 or fields[1:4] != ["FLOCK", "ADVISORY", "WRITE"]:
                    continue
                major, minor, inode = fields[5].split(":")
                if (int(major, 16), int(minor, 16), int(inode)) == (
                    os.major(info.st_dev),
                    os.minor(info.st_dev),
                    info.st_ino,
                ):
                    held = int(fields[4]) == pid
                    break
            values = dict(observed.value)
            if matches and held and matching_process():
                values.update(ownership="live", ownership_evidence="kernel_owner_lock")
                return OperatorObservation(
                    observed.owner,
                    observed.observed_at,
                    started,
                    "current",
                    "available",
                    values,
                )
            if matches:
                return unavailable("legacy_process_lock_unproven")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return unavailable("native_owner_lock_held")
            values.update(
                ownership="unproven", ownership_evidence="vacant_native_owner_lock"
            )
            return OperatorObservation(
                observed.owner,
                observed.observed_at,
                started,
                "current",
                "available",
                values,
                "service_stopped",
            )
        finally:
            os.close(descriptor)
    except (OSError, sqlite3.Error, ValueError):
        return unavailable("adoption_owner_evidence_unavailable")


def inspect_service_settlement(
    root: str | Path, *, expected_root_id: str, include_pending_poll: bool = True
) -> OperatorObservation:
    """Observe retained native effects without stopping or initializing a role.

    This is host-local evidence, independent of the coordinator's acknowledgement
    projection. A pending agent poll is unresolved work, even with no CPU use.
    Supervisor launches must have native terminal containment evidence. Missing
    or incompatible records produce unavailable evidence, never an empty root.
    ``include_pending_poll=False`` observes assignment/containment settlement
    while a service remains accepting maintenance checks; its ordinary empty
    work poll is not a previous check's effect. Service replacement always uses
    the default, which also requires that poll to settle.
    """
    root = Path(root)
    owner = inspect_native_service(root, expected_root_id=expected_root_id)
    waits: list[str] = []
    if owner.availability != "available":
        return owner
    try:
        with _readonly_root(root) as conn:
            if owner.value["role"] == "coordinator":
                if _retained_coordinator_operations(conn):
                    waits.append("accepted_work_or_preparation")
                if conn.execute(
                    "SELECT 1 FROM agent_coordinator_references WHERE resolved = 0 LIMIT 1"
                ).fetchone():
                    waits.append("assignment_or_release")
                if conn.execute(
                    "SELECT 1 FROM agent_controls WHERE state IN ('pending_delivery','applying') OR acknowledged = 0 LIMIT 1"
                ).fetchone():
                    waits.append("control_settlement")
            elif owner.value["role"] == "local-agent":
                if conn.execute(
                    "SELECT 1 FROM agent_session_references WHERE reference_kind = 'delivery' AND resolved = 0 LIMIT 1"
                ).fetchone():
                    waits.append("local_assignment_or_release")
                if (
                    include_pending_poll
                    and conn.execute(
                        "SELECT 1 FROM agent_poll_state_local p WHERE state = 'PENDING' OR (state = 'FENCED' AND result_json IS NULL AND EXISTS (SELECT 1 FROM agent_sessions_local s WHERE s.session_id = p.session_id AND s.state = 'ACTIVE')) LIMIT 1"
                    ).fetchone()
                ):
                    waits.append("unresolved_poll")
                database = root / "supervisor" / "supervisor.sqlite"
                with sqlite3.connect(
                    database.resolve().as_uri() + "?mode=ro", uri=True
                ) as supervisor:
                    if supervisor.execute(
                        "SELECT 1 FROM launches WHERE state NOT IN ('contained','exited') LIMIT 1"
                    ).fetchone():
                        waits.append("supervisor_containment")
            else:
                raise ValueError("unsupported service role")
    except (OSError, sqlite3.Error, ValueError, KeyError, json.JSONDecodeError):
        return OperatorObservation(
            owner.owner,
            owner.observed_at,
            owner.revision,
            "unknown",
            "unavailable",
            {},
            "settlement_evidence_unavailable",
        )
    return OperatorObservation(
        owner.owner,
        owner.observed_at,
        owner.revision,
        "current",
        "available",
        {"settled": not waits, "wait_reasons": cast(list[PlainData], waits)},
    )
