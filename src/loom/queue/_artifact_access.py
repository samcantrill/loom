"""Exact authority-backed file reads; no caller-controlled source locations."""

from __future__ import annotations

import base64
import codecs
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, cast

from loom.io.uris import uri_to_path
from loom.io.errors import UnsupportedURIError
from loom.pipeline.stores.errors import ArtifactStoreError
from loom.pipeline.stores import shared_artifacts as shared
from loom.runs.outputs import OutputLocator, OutputSelection
from loom.runs.query import RunQuery
from ._output_selection import _rows

ARTIFACT_OPERATIONS = frozenset(
    {"describe_artifact", "read_artifact_chunk", "read_artifact"}
)
MAX_CHUNK = 256 * 1024


class AccessFailure(Exception):
    def __init__(self, outcome: str):
        self.outcome = outcome


def validate_artifact_request(operation: str, payload: Any) -> dict[str, Any]:
    common = {"locator", "scope"}
    extra = {
        "describe_artifact": {"cursor", "limit", "declaration"},
        "read_artifact_chunk": {"declaration", "member", "offset", "length"},
        "read_artifact": {"member", "format", "limit"},
    }[operation]
    if (
        not isinstance(payload, dict)
        or set(payload) - common - extra
        or "locator" not in payload
    ):
        raise ValueError("invalid artifact request")
    value = dict(payload)
    value["locator"] = OutputLocator.from_dict(value["locator"])
    value["scope"] = (
        RunQuery(scope=value.get("scope", {"kind": "managed"})).checked().scope
    )
    if operation == "describe_artifact":
        value.setdefault("cursor", 0)
        value.setdefault("limit", 100)
        value.setdefault("declaration", None)
        numbers = {"cursor": (0, 2**63 - 1), "limit": (1, 200)}
    elif operation == "read_artifact_chunk":
        if not {"declaration", "member", "offset", "length"} <= set(value):
            raise ValueError("chunk requires declaration, member, offset and length")
        numbers = {"offset": (0, 2**63 - 1), "length": (1, MAX_CHUNK)}
    else:
        value.setdefault("format", "text")
        value.setdefault("limit", MAX_CHUNK)
        if value["format"] not in ("text", "json", "bytes"):
            raise ValueError("invalid preview format")
        numbers = {"limit": (1, MAX_CHUNK)}
    for key, (low, high) in numbers.items():
        if type(value[key]) is not int or not low <= value[key] <= high:
            raise ValueError("invalid artifact limit")
    if value.get("member") is not None:
        try:
            shared.relative(value["member"])
        except ArtifactStoreError as exc:
            raise ValueError("invalid artifact member") from exc
    if value.get("declaration") is not None and (
        not isinstance(value["declaration"], str)
        or len(value["declaration"]) != 64
        or any(c not in "0123456789abcdef" for c in value["declaration"])
    ):
        raise ValueError("invalid declaration identity")
    if (
        operation == "read_artifact_chunk"
        or operation == "describe_artifact"
        and value["cursor"]
    ) and value.get("declaration") is None:
        raise ValueError("continuation requires declaration identity")
    return value


def _open_member(root: Path, member: str) -> int:
    """Traverse opened directory descriptors so rename/symlink races cannot escape."""
    parts = [*root.absolute().parts[1:], *shared.relative(member).split("/")]
    fd = os.open(root.anchor or "/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = child
        result = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd
        )
        if not stat.S_ISREG(os.fstat(result).st_mode):
            os.close(result)
            raise AccessFailure("unsupported_closure")
        return result
    finally:
        os.close(fd)


def _resolve(
    daemon: Any, value: dict[str, Any], *, verify: bool
) -> tuple[Path, dict[str, Any]]:
    locator = value["locator"]
    rows = _rows(
        daemon,
        OutputSelection(locator=locator, scope=value["scope"]),
        locator.run_uri,
        commits=False,
    )
    selected = next((r for r in rows if r["outcome"] == "selected"), None)
    if selected is None:
        raise AccessFailure("unavailable")
    from loom.artifacts import ArtifactRef

    ref = ArtifactRef.from_dict(selected["artifact"])
    binding = shared.binding(ref.metadata)
    if binding is not None:
        roots = daemon.config.coordinator_shared_roots
        try:
            primary = shared.reference_path(binding, roots)
        except ArtifactStoreError as exc:
            raise AccessFailure("unavailable") from exc
        root = primary
        for _ in str(binding["primary"]).split("/"):
            root = root.parent
        raw = shared.receipt_bytes(
            shared.contained(root, shared.RECEIPT),
            shared.budgets(binding["budgets"])["max_manifest_bytes"],
        )
        if hashlib.sha256(raw).hexdigest() != binding["receipt_digest"]:
            raise AccessFailure("integrity_failed")
        receipt = json.loads(raw)
        if verify:
            # Distinguish missing companions from present but corrupt bytes.
            for member in receipt["members"]:
                os.close(_open_member(root, member["path"]))
            receipt = shared.read_receipt(root, binding)
        declaration = str(binding["receipt_digest"])
        members = cast(list[dict[str, Any]], receipt["members"])
        primary_name = str(binding["primary"])
        verification = "recorded_sha256"
    else:
        try:
            path = uri_to_path(ref.uri)
            root = uri_to_path(locator.run_uri) / "artifacts"
            member = path.relative_to(root).as_posix()
        except (ValueError, UnsupportedURIError) as exc:
            raise AccessFailure("unsupported_backend") from exc
        fd = _open_member(root, member)
        try:
            info = os.fstat(fd)
            digest = ref.checksum.removeprefix("sha256:") if ref.checksum else None
            if verify and digest is not None:
                with os.fdopen(os.dup(fd), "rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                        raise AccessFailure("integrity_failed")
            members = [{"path": member, "size_bytes": info.st_size, "digest": digest}]
            declaration = hashlib.sha256(
                shared.encoded(
                    [
                        locator.to_dict(),
                        ref.to_dict(),
                        members,
                        info.st_mtime_ns,
                        info.st_ctime_ns,
                        info.st_ino,
                    ]
                )
            ).hexdigest()
            members[0]["_stat"] = (
                info.st_ino,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
            )
        finally:
            os.close(fd)
        primary_name = member
        verification = "recorded_sha256" if ref.checksum else "unverified_original"
    if value.get("declaration") not in (None, declaration):
        raise AccessFailure("integrity_failed")
    return root, {
        "outcome": "available",
        "locator": locator.to_dict(),
        "declaration": declaration,
        "primary": primary_name,
        "total_bytes": sum(m["size_bytes"] for m in members),
        "members": members,
        "verification": verification,
    }


def _read(
    root: Path,
    member: dict[str, Any],
    offset: int,
    length: int,
    *,
    verify: bool = False,
) -> bytes:
    fd = _open_member(root, member["path"])
    try:
        before = os.fstat(fd)
        if member.get("_stat") not in (
            None,
            (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns),
        ):
            raise AccessFailure("integrity_failed")
        if before.st_size != member["size_bytes"] or offset > before.st_size:
            raise AccessFailure("integrity_failed")
        data = os.pread(fd, length, offset)
        if verify and member["digest"] is not None:
            with os.fdopen(os.dup(fd), "rb") as stream:
                if (
                    hashlib.file_digest(stream, "sha256").hexdigest()
                    != member["digest"]
                ):
                    raise AccessFailure("integrity_failed")
        after = os.fstat(fd)
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise AccessFailure("integrity_failed")
        return data
    finally:
        os.close(fd)


def artifact_operation(
    daemon: Any, operation: str, value: dict[str, Any]
) -> dict[str, Any]:
    """Every invocation resolves authorization and the exact retained commit anew."""
    failure = {"locator": value["locator"].to_dict(), "verification": "not_verified"}
    try:
        root, description = _resolve(
            daemon, value, verify=operation != "read_artifact_chunk"
        )
        members = description.pop("members")
        if operation == "describe_artifact":
            start, limit = value["cursor"], value["limit"]
            page = []
            size = 0
            for member in members[start : start + limit]:
                member = {key: member[key] for key in ("path", "size_bytes", "digest")}
                cost = len(shared.encoded(member))
                if page and size + cost > 512 * 1024:
                    break
                page.append(member)
                size += cost
            end = start + len(page)
            return {
                **description,
                "members": page,
                "next_cursor": end if end < len(members) else None,
            }
        name = value.get("member") or description["primary"]
        member = next((m for m in members if m["path"] == name), None)
        if member is None:
            raise AccessFailure("unavailable")
        if operation == "read_artifact_chunk":
            data = _read(root, member, value["offset"], value["length"])
            return {
                **description,
                "member": name,
                "offset": value["offset"],
                "data": base64.b64encode(data).decode(),
                "eof": value["offset"] + len(data) == member["size_bytes"],
            }
        limit, format_ = value["limit"], value["format"]
        if format_ == "json" and member["size_bytes"] > limit:
            return {**description, "outcome": "too_large", "member": name}
        data = _read(root, member, 0, limit, verify=True)
        truncated = len(data) < member["size_bytes"]
        if format_ == "bytes":
            content = base64.b64encode(data).decode()
        elif format_ == "text":
            content = codecs.getincrementaldecoder("utf-8")("strict").decode(
                data, final=not truncated
            )
        else:
            content = json.loads(
                data.decode("utf-8"),
                parse_constant=lambda _: (_ for _ in ()).throw(
                    ValueError("nonfinite JSON")
                ),
            )
        result = {
            **description,
            "member": name,
            "format": format_,
            "content": content,
            "truncated": truncated,
        }
        if len(shared.encoded(result)) > 768 * 1024:
            if format_ == "text":
                while len(shared.encoded(result)) > 768 * 1024:
                    result["content"] = result["content"][: len(result["content"]) // 2]
                result["truncated"] = True
            else:
                return {**description, "outcome": "too_large", "member": name}
        return result
    except AccessFailure as exc:
        return {**failure, "outcome": exc.outcome}
    except ArtifactStoreError:
        return {**failure, "outcome": "integrity_failed"}
    except OSError:
        return {**failure, "outcome": "unavailable"}
    except (UnicodeError, ValueError, RecursionError):
        return {**failure, "outcome": "invalid_content"}
