"""Client-owned temporary downloads and atomic non-replacing publication."""

from __future__ import annotations

import base64
from collections.abc import Iterable
import ctypes
import errno
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any

from loom.pipeline.stores.shared_artifacts import relative
from loom.runs.outputs import OutputLocator
from loom.queue._coordinator_control import CoordinatorClientError


def _publish(source: Path, target: Path) -> None:
    # POSIX rename may replace an empty directory. RENAME_NOREPLACE is atomic
    # even when another fetch or user creates the destination concurrently.
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    if rename is None:
        raise OSError(errno.ENOTSUP, "atomic directory publication unavailable")
    rename.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(target))


def fetch_artifacts(
    client: Any,
    selections: Iterable[Any],
    destination: str | Path,
    *,
    scope: Any,
    expected_coordinator_id: str | None,
    deadline: float | None = None,
) -> dict[str, Any]:
    def check_deadline() -> None:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("artifact fetch deadline exceeded")

    root = Path(destination).absolute()
    results: list[dict[str, Any]] = []
    completed: dict[str, dict[str, Any]] = {}
    options = {"scope": scope, "expected_coordinator_id": expected_coordinator_id}
    if deadline is not None:
        options["deadline"] = deadline
    for selection in selections:
        row = selection.to_dict() if hasattr(selection, "to_dict") else dict(selection)
        result = {**row, "verification": "not_verified"}
        pending = None
        try:
            if row.get("outcome", "selected") != "selected":
                results.append(result)
                continue
            locator = OutputLocator.from_dict(row.get("locator", row))
            result["locator"] = locator.to_dict()
            check_deadline()
            description = client.describe_artifact(locator, **options)
            check_deadline()
            result.update(
                {
                    k: v
                    for k, v in description.items()
                    if k not in {"members", "next_cursor"}
                }
            )
            if description["outcome"] != "available":
                results.append(result)
                continue
            declaration = description["declaration"]
            if declaration in completed:
                result.update(completed[declaration])
                result["primary_path"] = str(
                    Path(result["local_path"]) / relative(description["primary"])
                )
                results.append(result)
                continue
            members = list(description["members"])
            cursor = description["next_cursor"]
            while cursor is not None:
                check_deadline()
                page = client.describe_artifact(
                    locator, cursor=cursor, declaration=declaration, **options
                )
                check_deadline()
                if page["outcome"] != "available":
                    result["outcome"] = page["outcome"]
                    raise _TransferFailure
                members.extend(page["members"])
                cursor = page["next_cursor"]
            check_deadline()
            root.mkdir(parents=True, exist_ok=True)
            target = root / declaration
            if target.exists() or target.is_symlink():
                raise FileExistsError(str(target))
            pending = Path(tempfile.mkdtemp(prefix=".loom-fetch-", dir=root))
            seen: set[str] = set()
            for member in members:
                check_deadline()
                name = relative(member["path"])
                if name in seen:
                    raise ValueError("duplicate declaration member")
                seen.add(name)
                path = pending / name
                path.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                offset = 0
                with path.open("xb") as sink:
                    while offset < member["size_bytes"]:
                        length = min(256 * 1024, member["size_bytes"] - offset)
                        chunk: dict[str, Any] = {}
                        for retry in range(2):
                            try:
                                check_deadline()
                                chunk = client.read_artifact_chunk(
                                    locator,
                                    declaration=declaration,
                                    member=name,
                                    offset=offset,
                                    length=length,
                                    **options,
                                )
                                break
                            except CoordinatorClientError as exc:
                                if retry or exc.code not in {
                                    "unavailable",
                                    "timeout",
                                    "transport_error",
                                }:
                                    raise
                        check_deadline()
                        if chunk["outcome"] != "available":
                            result["outcome"] = chunk["outcome"]
                            raise _TransferFailure
                        data = base64.b64decode(chunk["data"], validate=True)
                        if (
                            len(data) != length
                            or chunk["offset"] != offset
                            or chunk["declaration"] != declaration
                        ):
                            result["outcome"] = "integrity_failed"
                            raise _TransferFailure
                        check_deadline()
                        sink.write(data)
                        digest.update(data)
                        offset += len(data)
                if (
                    member["digest"] is not None
                    and digest.hexdigest() != member["digest"]
                ):
                    result["outcome"] = "integrity_failed"
                    raise _TransferFailure
            check_deadline()
            _publish(pending, target)
            pending = None
            local = {
                "outcome": "available",
                "local_path": str(target),
                "verification": description["verification"],
            }
            completed[declaration] = local
            result.update(local)
            result["primary_path"] = str(target / relative(description["primary"]))
        except FileExistsError:
            result["outcome"] = "destination_exists"
        except _TransferFailure:
            pass
        except (OSError, ValueError, KeyError, TypeError, CoordinatorClientError):
            result["outcome"] = "failed"
        finally:
            if pending is not None:
                try:
                    shutil.rmtree(pending)
                except OSError:
                    result["partial_path"] = str(pending)
        results.append(result)
    successes = sum(r["outcome"] == "available" for r in results)
    return {
        "items": results,
        "complete": True,
        "success_count": successes,
        "failure_count": len(results) - successes,
        "location_context": "client_process_filesystem",
    }


class _TransferFailure(Exception):
    pass
