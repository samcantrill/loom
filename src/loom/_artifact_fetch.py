"""Client-owned temporary downloads and atomic non-replacing publication."""

from __future__ import annotations

from contextlib import nullcontext
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

from loom._artifact_ranges import TransferFailure, copy_member, transfer_readers
from loom.pipeline.stores.shared_artifacts import encoded, relative
from loom.runs.outputs import OutputLocator
from loom.queue._coordinator_control import CoordinatorClientError
from loom.queue._coordinator_transport import HttpsControlTransport


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
    check_scratch: bool = False,
) -> dict[str, Any]:
    """check_scratch selects an exclusive, owner-private fleet-check destination."""

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
            if options["expected_coordinator_id"] is None:
                connection = client._native_call("handshake", {}, deadline=deadline)
                options["expected_coordinator_id"] = connection.coordinator_id
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
            if description["verification"] == "producer_declared":
                # The receipt intentionally does not enumerate companion files.
                # Do not return an incomplete download as a complete closure.
                result["outcome"] = "unsupported_backend"
                result["reason"] = (
                    "trusted_shared_storage_requires_shared_filesystem_access"
                )
                results.append(result)
                continue
            declaration = description["declaration"]
            if len(declaration) != 64 or any(
                c not in "0123456789abcdef" for c in declaration
            ):
                raise TransferFailure("integrity_failed")
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
                    raise TransferFailure(page["outcome"])
                members.extend(page["members"])
                cursor = page["next_cursor"]
            check_deadline()
            root.mkdir(parents=True, exist_ok=True)
            target = root / declaration
            if target.exists() or target.is_symlink():
                if not check_scratch:
                    raise FileExistsError(str(target))
                # This private target was published immediately before an
                # interruption. Accept only the exact complete verified closure.
                if not _valid_private_target(target, members, check_deadline):
                    if target.is_symlink() or not target.is_dir():
                        target.unlink()
                    else:
                        shutil.rmtree(target)
            if not target.exists():
                pending = Path(tempfile.mkdtemp(prefix=".loom-fetch-", dir=root))
                seen: set[str] = set()
                progress = {"received_bytes": 0, "reused_bytes": 0}
                if check_scratch:
                    result["transfer"] = progress
                transport = getattr(client, "_transport", None)
                session = (
                    transport.range_reads()
                    if isinstance(transport, HttpsControlTransport)
                    else nullcontext()
                )
                with session, transfer_readers(options["expected_coordinator_id"] if check_scratch else None) as readers:
                    for member in members:
                        check_deadline()
                        name = relative(member["path"])
                        if name in seen:
                            raise ValueError("duplicate declaration member")
                        seen.add(name)
                        path = pending / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        cache = None
                        if check_scratch:
                            key = hashlib.sha256(
                                encoded([locator.to_dict(), declaration, member])
                            ).hexdigest()
                            cache = root / ".ranges" / key
                        copy_member(
                            client,
                            locator,
                            options,
                            declaration,
                            member,
                            path,
                            cache,
                            readers,
                            check_deadline,
                            progress,
                        )
                        if not _matches_member(path, member, check_deadline):
                            if cache is not None:
                                shutil.rmtree(cache, ignore_errors=True)
                            raise TransferFailure("integrity_failed")
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
        except TransferFailure as exc:
            result["outcome"] = exc.outcome
        except (TimeoutError, CoordinatorClientError) as error:
            outcome = "failed"
            if check_scratch:
                if deadline is not None and time.monotonic() >= deadline:
                    outcome = "deadline_exceeded"
                elif isinstance(error, CoordinatorClientError):
                    if error.code == "deadline_exceeded":
                        outcome = "transport_deadline_exceeded"
                    elif error.code == "capacity_exhausted":
                        outcome = error.code
            result["outcome"] = outcome
        except (OSError, ValueError, KeyError, TypeError):
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


def _matches_member(path, member, check_time):
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size != member["size_bytes"]
    ):
        return False
    if member["digest"] is None:
        return True
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            check_time()
            digest.update(chunk)
    return digest.hexdigest() == member["digest"]


def _valid_private_target(target, members, check_time):
    if target.is_symlink() or not target.is_dir():
        return False
    expected = {relative(m["path"]) for m in members}
    actual = {
        str(p.relative_to(target))
        for p in target.rglob("*")
        if p.is_symlink() or not p.is_dir()
    }
    if actual != expected:
        return False
    for m in members:
        check_time()
        if m["digest"] is None or not _matches_member(
            target / relative(m["path"]), m, check_time
        ):
            return False
    check_time()
    return True
