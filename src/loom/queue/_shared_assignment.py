"""Immutable control payloads, owned and retained by native assignment delivery.

References authorize no execution. Their verified full bundle still traverses
profile, claim, acceptance and start-permit validation. No collector owns these
files: retained delivery history continues to require them after termination.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
import stat
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from loom.serialization import PlainData, thaw_plain_data
from .errors import QueueConflictError, QueueServiceError
from .shared_execution import location, qualifications

if TYPE_CHECKING:
    from ._remote_stage_execution import (
        _ResidentAssignmentBundle,
        ResidentExecutionProfile,
        ResidentProfileDescriptor,
    )

CAPABILITY = "shared-assignment-reference-v1"
KIND = "loom.shared-assignment-reference"


def reference(value: object) -> dict[str, PlainData] | None:
    if not isinstance(value, Mapping) or "kind" not in value:
        return None
    fields = {
        "kind",
        "schema_version",
        "location",
        "sha256",
        "size_bytes",
        "assignment_id",
        "attempt_id",
        "session_id",
        "issuer_epoch",
        "profile_id",
        "profile_fingerprint",
    }
    if (
        set(value) != fields
        or value.get("kind") != KIND
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != 1
    ):
        raise QueueServiceError(
            "shared assignment reference version or fields are unsupported"
        )
    for key in fields - {"schema_version", "location", "size_bytes"}:
        if not isinstance(value[key], str) or not value[key]:
            raise QueueServiceError("shared assignment reference identity is invalid")
    for key in ("sha256", "profile_fingerprint"):
        if len(value[key]) != 64 or any(
            c not in "0123456789abcdef" for c in value[key]
        ):
            raise QueueServiceError("shared assignment reference digest is invalid")
    if type(value["size_bytes"]) is not int or value["size_bytes"] < 0:
        raise QueueServiceError("shared assignment reference size is invalid")
    return {
        **cast(dict[str, PlainData], dict(value)),
        "location": location(value["location"]),
    }


def require_root(
    root_id: str | None,
    roots: Mapping[str, PlainData],
    profile: ResidentProfileDescriptor,
) -> None:
    if root_id is None:
        raise QueueServiceError(
            "shared remote assignments require assignment_payload_root_id"
        )
    root = roots.get(root_id)
    if not isinstance(root, Mapping) or root.get("access") != "rw":
        raise QueueServiceError("assignment payload root must be mapped and writable")
    selected = qualifications({root_id: root})[root_id]
    remote = profile.shared_roots.get(root_id)
    if (
        not isinstance(remote, Mapping)
        or remote.get("challenge")
        != cast(Mapping[str, PlainData], selected)["challenge"]
    ):
        raise QueueServiceError(
            "assignment payload root is not qualified by the resident profile"
        )


def _directory(
    root: Mapping[str, PlainData], path: str, *, create: bool = False
) -> tuple[int, str]:
    # Walk by directory descriptors so neither a replaced parent nor a symlink
    # can redirect an open/publication outside the protected mapping.
    parts = path.split("/")
    fd = os.open(str(root["host_path"]), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                    os.fsync(fd)
                except FileExistsError:
                    pass
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = child
        return fd, parts[-1]
    except BaseException:
        os.close(fd)
        raise


def _read(fd: int, name: str, size: int) -> bytes:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise QueueServiceError("shared assignment payload must be a regular file")
        data = stream.read(size + 1)
    if len(data) != size:
        raise QueueConflictError("shared assignment payload size mismatch")
    return data


def publish(
    encoded: str,
    request: _ResidentAssignmentBundle,
    *,
    root_id: str,
    roots: Mapping[str, PlainData],
    session_id: str,
    issuer_epoch: str,
) -> dict[str, PlainData]:
    data = encoded.encode("utf-8")
    identity = hashlib.sha256(request.assignment_id.encode()).hexdigest()
    item = location(
        {
            "kind": "loom.shared-location",
            "schema_version": 1,
            "root_id": root_id,
            "path": f".loom-assignment-payloads/{identity}.json",
        }
    )
    try:
        fd, name = _directory(
            cast(Mapping[str, PlainData], roots[root_id]),
            str(item["path"]),
            create=True,
        )
        temporary = f".{name}.{uuid4().hex}.tmp"
        try:
            output = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=fd
            )
            with os.fdopen(output, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(
                    temporary, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False
                )
            except FileExistsError:
                if _read(fd, name, len(data)) != data:
                    raise QueueConflictError(
                        "shared assignment publication conflicts with retained bytes"
                    )
            os.fsync(fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=fd)
            finally:
                os.close(fd)
    except OSError as exc:
        raise QueueServiceError(
            "shared assignment payload publication is unavailable"
        ) from exc
    return {
        "kind": KIND,
        "schema_version": 1,
        "location": item,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "assignment_id": request.assignment_id,
        "attempt_id": request.attempt_id,
        "session_id": session_id,
        "issuer_epoch": issuer_epoch,
        "profile_id": request.profile.profile_id,
        "profile_fingerprint": request.profile.fingerprint,
    }


def verify_bundle(
    ref: Mapping[str, PlainData], request: _ResidentAssignmentBundle, *, session_id: str
) -> None:
    encoded = json.dumps(
        request.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    if (
        ref["session_id"] != session_id
        or request.assignment_id != ref["assignment_id"]
        or request.attempt_id != ref["attempt_id"]
        or request.profile.profile_id != ref["profile_id"]
        or request.profile.fingerprint != ref["profile_fingerprint"]
        or len(encoded) != ref["size_bytes"]
        or hashlib.sha256(encoded).hexdigest() != ref["sha256"]
    ):
        raise QueueConflictError(
            "shared assignment bundle conflicts with authenticated reference"
        )


def resolve(
    ref: Mapping[str, PlainData], profile: ResidentExecutionProfile, *, session_id: str
) -> _ResidentAssignmentBundle:
    from ._remote_stage_execution import _ResidentAssignmentBundle

    if (
        ref["session_id"] != session_id
        or ref["profile_id"] != profile.descriptor.profile_id
        or ref["profile_fingerprint"] != profile.descriptor.fingerprint
    ):
        raise QueueConflictError(
            "shared assignment reference has no exact protected profile"
        )
    item = cast(Mapping[str, PlainData], ref["location"])
    root_id = str(item["root_id"])
    root = profile.shared_roots.get(root_id)
    if not isinstance(root, Mapping):
        raise QueueServiceError("shared assignment payload root is not mapped")
    if qualifications({root_id: root}) != {
        root_id: profile.descriptor.shared_roots[root_id]
    }:
        raise QueueConflictError("shared assignment root qualification changed")
    try:
        fd, name = _directory(root, str(item["path"]))
        try:
            data = _read(fd, name, cast(int, ref["size_bytes"]))
        finally:
            os.close(fd)
    except OSError as exc:
        raise QueueServiceError("shared assignment payload is unavailable") from exc
    if hashlib.sha256(data).hexdigest() != ref["sha256"]:
        raise QueueConflictError("shared assignment payload digest mismatch")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise QueueServiceError(
                    "shared assignment JSON contains duplicate keys"
                )
            result[key] = value
        return result

    def invalid(value: str) -> object:
        raise QueueServiceError("shared assignment JSON contains non-finite numbers")

    try:
        value = json.loads(data, object_pairs_hook=pairs, parse_constant=invalid)
        request = _ResidentAssignmentBundle.from_remote_dict(thaw_plain_data(value))
    except (ValueError, UnicodeError) as exc:
        raise QueueServiceError("shared assignment JSON is invalid") from exc
    verify_bundle(ref, request, session_id=session_id)
    return request
