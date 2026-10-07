"""Bounded reads of authorized, attempt-qualified retained native log references."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import os
from pathlib import Path
from typing import Any

from loom.pipeline.stores.errors import StoreError
from loom.pipeline.stores.authority import AuthorityStoreError
from loom.pipeline.stores.local_runs import LocalRunStore
from loom.timestamps import utc_timestamp

from ._artifact_access import _open_member, AccessFailure
from ._output_selection import _authority

LOG_CAPABILITY = "bounded-run-logs-v1"
MAX_LOG_BYTES = 64 * 1024
_READ_ERRORS = (OSError, ValueError, LookupError, StoreError, AuthorityStoreError)


def validate_log_selection(stage: object, stream: object, tail: object) -> None:
    if (
        not isinstance(stage, str)
        or not stage
        or stage in {".", ".."}
        or any(c in stage for c in ("/", "\\", "\x00"))
    ):
        raise ValueError("stage must be a native stage name")
    if stream not in ("stdout", "stderr", "both"):
        raise ValueError("invalid log stream")
    if type(tail) is not int or tail <= 0:
        raise ValueError("tail must be a positive line count")


def _tail(path: Path, lines: int) -> dict[str, Any]:
    # Descriptor traversal shares the artifact reader's no-symlink/file-only
    # boundary. Read a suffix, never materialize the entire log or a huge line.
    fd = _open_member(path.parent, path.name)
    try:
        size = os.fstat(fd).st_size
        offset = max(0, size - MAX_LOG_BYTES)
        data = os.pread(fd, MAX_LOG_BYTES, offset)
    finally:
        os.close(fd)
    chunks = data.splitlines(keepends=True)
    selected = b"".join(chunks[-lines:])
    truncated = offset > 0 or len(selected) < len(data)
    try:
        text = selected.decode("utf-8")
        replaced = False
    except UnicodeDecodeError:
        text = selected.decode("utf-8", errors="replace")
        replaced = True
    # Replacement characters can triple the size; the returned UTF-8 text
    # must satisfy the same cap, keeping the most recent complete characters.
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_LOG_BYTES:
        text = encoded[-MAX_LOG_BYTES:].decode("utf-8", errors="ignore")
        truncated = True
    return {
        "availability": "available",
        "text": text,
        "truncated": truncated,
        "decoding_replaced": replaced,
    }


def read_logs(daemon: Any, value: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve a run operation through managed admission and current authority.

    Paths never come from the request or appear in the reply. A retained worker
    result qualifies the reference by run, stage and latest authority attempt.
    An unreachable retained file is not an empty successful stream.
    """
    from ._coordinator_control import control_error

    operation = daemon.operation(value["operation_id"])
    if operation.kind != "run":
        raise control_error("invalid_request", "read_run_logs", value)
    retained = operation.result.get("admission")
    streams = ("stdout", "stderr") if value["stream"] == "both" else (value["stream"],)
    observed = utc_timestamp()
    result: dict[str, Any] = {
        "operation_id": operation.operation_id,
        "admission_id": None,
        "stage": value["stage"],
        "attempt": None,
        "observed_at": observed,
        "owner": "coordinator",
        "freshness": "retained",
        "authority_revision": None,
        "streams": [],
    }
    availability = (
        "pending"
        if operation.state in {"pending", "running", "accepted"}
        else "missing"
    )
    worker = None
    if isinstance(retained, Mapping):
        admission = daemon.admission(retained["admission_id"]).admission
        # Match inspect_run's managed-run authorization before any file access.
        daemon.admission_for_run_uri(admission.run_uri)
        result["admission_id"] = admission.admission_id
        try:
            snapshot = _authority(daemon, admission.run_uri).open_run(admission.run_uri)
            result["authority_revision"] = snapshot.revision.sequence
            stage = next(
                (s for s in snapshot.stages if s.stage_name == value["stage"]), None
            )
            if stage is None:
                raise control_error("not_found", "read_run_logs", value)
            result["attempt"] = stage.attempts[-1].attempt if stage.attempts else None
            availability = (
                "missing"
                if stage.status.value
                in {"SUCCEEDED", "FAILED", "CANCELLED", "SKIPPED", "BLOCKED"}
                else "pending"
            )
            if result["attempt"] is not None:
                worker = LocalRunStore(
                    daemon.config.run_store_root
                ).read_stage_worker_result(
                    admission.run_uri, stage.stage_name, attempt=result["attempt"]
                )
        except _READ_ERRORS:
            availability = "unavailable"
    for stream in streams:
        entry = {
            "stream": stream,
            "log_id": None,
            "source": "retained_worker_result",
            "availability": availability,
            "text": None,
            "truncated": False,
            "decoding_replaced": False,
        }
        ref = None if worker is None else worker.get(f"{stream}_path")
        if isinstance(ref, str) and Path(ref).is_absolute():
            entry["log_id"] = hashlib.sha256(
                f"{result['admission_id']}\0{value['stage']}\0{result['attempt']}\0{stream}\0{ref}".encode()
            ).hexdigest()
            try:
                entry.update(_tail(Path(ref), value["tail"]))
            except FileNotFoundError:
                entry["availability"] = "missing"
            except (OSError, ValueError, AccessFailure):
                entry["availability"] = "unavailable"
        elif worker is not None:
            entry["availability"] = "missing"
        result["streams"].append(entry)
    return result


def decode_logs(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate only the new response; existing native response shapes stay strict."""
    if set(value) != {
        "operation_id",
        "admission_id",
        "stage",
        "attempt",
        "observed_at",
        "owner",
        "freshness",
        "authority_revision",
        "streams",
    }:
        raise ValueError("invalid log result fields")
    for key in ("operation_id", "stage", "observed_at", "owner"):
        if not isinstance(value[key], str) or not value[key]:
            raise ValueError("invalid log identity")
    if value["admission_id"] is not None and not isinstance(value["admission_id"], str):
        raise ValueError("invalid log admission")
    if value["attempt"] is not None and (
        type(value["attempt"]) is not int or value["attempt"] < 1
    ):
        raise ValueError("invalid log attempt")
    if value["freshness"] != "retained" or (
        value["authority_revision"] is not None
        and (
            type(value["authority_revision"]) is not int
            or value["authority_revision"] < 0
        )
    ):
        raise ValueError("invalid log freshness")
    streams = value["streams"]
    if not isinstance(streams, list) or not 1 <= len(streams) <= 2:
        raise ValueError("invalid log streams")
    seen = set()
    for entry in streams:
        if not isinstance(entry, Mapping) or set(entry) != {
            "stream",
            "log_id",
            "source",
            "availability",
            "text",
            "truncated",
            "decoding_replaced",
        }:
            raise ValueError("invalid log stream fields")
        stream = entry["stream"]
        if stream not in ("stdout", "stderr") or stream in seen:
            raise ValueError("invalid log stream identity")
        seen.add(stream)
        if entry["source"] != "retained_worker_result" or entry["availability"] not in (
            "available",
            "pending",
            "missing",
            "unavailable",
        ):
            raise ValueError("invalid log availability")
        if entry["log_id"] is not None and (
            not isinstance(entry["log_id"], str)
            or len(entry["log_id"]) != 64
            or any(c not in "0123456789abcdef" for c in entry["log_id"])
        ):
            raise ValueError("invalid log source identity")
        if (
            type(entry["truncated"]) is not bool
            or type(entry["decoding_replaced"]) is not bool
        ):
            raise ValueError("invalid log flags")
        text = entry["text"]
        if entry["availability"] == "available":
            if (
                not isinstance(text, str)
                or len(text.encode("utf-8")) > MAX_LOG_BYTES
                or entry["log_id"] is None
            ):
                raise ValueError("invalid log text")
        elif text is not None:
            raise ValueError("unavailable log has text")
    return dict(value)
