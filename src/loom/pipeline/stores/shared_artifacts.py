"""Bounded regular-member closures for native shared artifact references.

The receipt is part of the immutable publication tree. References carry its
identity and digest, rather than a second catalog or copied consumer payload.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
from typing import cast

from loom.artifacts import ArtifactRef
from loom.serialization import PlainData, thaw_plain_data
from .errors import ArtifactStoreError

SHARED_PUBLICATION = "loom.shared_publication"
RECEIPT = ".loom-publication.json"


def budgets(value: object) -> dict[str, int]:
    """Decode positive finite operator limits, with no implicit unlimited mode."""
    keys = {"max_members", "max_payload_bytes", "max_manifest_bytes"}
    if (
        not isinstance(value, Mapping)
        or set(value) != keys
        or any(type(value[k]) is not int or value[k] <= 0 for k in keys)
    ):
        raise ArtifactStoreError(
            "shared publication requires positive integer member, payload and manifest budgets"
        )
    return {key: value[key] for key in sorted(keys)}


def relative(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value == "."
        or "\\" in value
        or "\x00" in value
        or PurePosixPath(value).is_absolute()
        or ".." in value.split("/")
        or str(PurePosixPath(value)) != value
    ):
        raise ArtifactStoreError(
            "shared publication requires normalized relative members"
        )
    return value


def contained(base: Path, value: str, *, exists: bool = True) -> Path:
    current = base
    if not base.is_dir() or base.is_symlink():
        raise ArtifactStoreError("shared publication root is unavailable")
    for part in PurePosixPath(relative(value)).parts:
        current /= part
        if current.is_symlink():
            raise ArtifactStoreError("shared publication does not admit symbolic links")
    if exists and not current.exists():
        raise ArtifactStoreError("shared publication member is missing")
    if not current.resolve().is_relative_to(base.resolve()):
        raise ArtifactStoreError("shared publication member escapes its root")
    return current


def file_identity(path: Path, *, max_bytes: int | None = None) -> tuple[int, str]:
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ArtifactStoreError("shared publication requires regular files")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode):
            raise ArtifactStoreError("shared publication requires regular files")
        if max_bytes is not None and details.st_size > max_bytes:
            raise ArtifactStoreError("shared publication exceeds member or payload budget")
        digest = hashlib.sha256()
        read_bytes = 0
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            while data := stream.read(1024 * 1024):
                read_bytes += len(data)
                if max_bytes is not None and read_bytes > max_bytes:
                    raise ArtifactStoreError("shared publication exceeds member or payload budget")
                digest.update(data)
        after = os.fstat(descriptor)
        if (details.st_size, details.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ArtifactStoreError("shared publication changed while reading")
        return details.st_size, digest.hexdigest()
    finally:
        os.close(descriptor)


def receipt_bytes(path: Path, limit: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode):
            raise ArtifactStoreError(
                "shared publication receipt must be a regular file"
            )
        if details.st_size > limit:
            raise ArtifactStoreError("shared publication exceeds manifest budget")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ArtifactStoreError("shared publication exceeds manifest budget")
        return data
    finally:
        os.close(descriptor)


def encoded(value: object) -> bytes:
    return json.dumps(
        thaw_plain_data(value), sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def binding(metadata: Mapping[str, PlainData]) -> dict[str, PlainData] | None:
    raw = metadata.get(SHARED_PUBLICATION)
    if raw is None:
        return None
    keys = {
        "schema_version",
        "root_id",
        "tree",
        "publication_id",
        "receipt_digest",
        "primary",
        "budgets",
    }
    if (
        not isinstance(raw, Mapping)
        or set(raw) != keys
        or type(raw["schema_version"]) is not int
        or raw["schema_version"] != 1
    ):
        raise ArtifactStoreError("shared publication reference schema is invalid")
    for key in ("root_id", "publication_id", "receipt_digest"):
        if not isinstance(raw[key], str) or not raw[key] or "/" in str(raw[key]):
            raise ArtifactStoreError("shared publication reference identity is invalid")
    if len(str(raw["receipt_digest"])) != 64 or any(
        c not in "0123456789abcdef" for c in str(raw["receipt_digest"])
    ):
        raise ArtifactStoreError("shared publication receipt digest is invalid")
    relative(raw["tree"])
    relative(raw["primary"])
    budgets(raw["budgets"])
    return cast(dict[str, PlainData], thaw_plain_data(raw))


def inventory(tree: Path, limits: Mapping[str, int]) -> list[dict[str, PlainData]]:
    members: list[dict[str, PlainData]] = []
    total = 0
    def unreadable(error: OSError) -> None:
        raise ArtifactStoreError("shared publication tree is unreadable") from error
    for directory, names, files in os.walk(tree, followlinks=False, onerror=unreadable):
        for name in names:
            path = Path(directory) / name
            if path.is_symlink() or not path.is_dir():
                raise ArtifactStoreError(
                    "shared publication contains an unsupported member"
                )
        for name in sorted(files):
            path = Path(directory) / name
            if path == tree / RECEIPT:
                continue
            if len(members) >= limits["max_members"]:
                raise ArtifactStoreError("shared publication exceeds member or payload budget")
            size, digest = file_identity(path, max_bytes=limits["max_payload_bytes"] - total)
            total += size
            members.append(
                {
                    "path": path.relative_to(tree).as_posix(),
                    "size_bytes": size,
                    "digest": digest,
                }
            )
    return sorted(members, key=lambda item: str(item["path"]))


def read_receipt(
    tree: Path,
    reference: Mapping[str, PlainData],
    *,
    limits: Mapping[str, int] | None = None,
) -> dict[str, PlainData]:
    selected = budgets(reference["budgets"]) if limits is None else budgets(limits)
    path = contained(tree, RECEIPT)
    data = receipt_bytes(path, selected["max_manifest_bytes"])
    if hashlib.sha256(data).hexdigest() != reference["receipt_digest"]:
        raise ArtifactStoreError("shared publication receipt integrity conflicts")
    receipt = json.loads(data)
    if (
        not isinstance(receipt, dict)
        or set(receipt)
        != {"schema_version", "publication_id", "identity", "members", "outputs"}
        or receipt["schema_version"] != 1
        or receipt["publication_id"] != reference["publication_id"]
        or not isinstance(receipt["outputs"], dict)
        or reference["primary"] not in receipt["outputs"].values()
    ):
        raise ArtifactStoreError("shared publication receipt identity conflicts")
    observed = inventory(tree, selected)
    if receipt["members"] != observed:
        raise ArtifactStoreError("shared publication closure integrity conflicts")
    paths = {str(item["path"]) for item in observed}
    if any(primary not in paths for primary in receipt["outputs"].values()):
        raise ArtifactStoreError("shared publication primary member is missing")
    return receipt


def reference_path(
    reference: Mapping[str, PlainData], roots: Mapping[str, PlainData]
) -> Path:
    """Resolve a native reference through its protected consumer mapping."""
    root = roots.get(str(reference["root_id"]))
    if not isinstance(root, Mapping) or root.get("publication") != reference["budgets"]:
        raise ArtifactStoreError("shared consumer root or budget is not admitted")
    tree = contained(Path(str(root["host_path"])), str(reference["tree"]))
    return contained(tree, str(reference["primary"]))


def resolve_binding(
    reference: Mapping[str, PlainData], roots: Mapping[str, PlainData]
) -> Path:
    """Resolve and verify one committed binding through a consumer's private roots."""
    primary = reference_path(reference, roots)
    tree = primary
    for _ in PurePosixPath(str(reference["primary"])).parts:
        tree = tree.parent
    read_receipt(tree, reference)
    return primary


def verify_ref(ref: ArtifactRef, primary: Path) -> None:
    """Validate every retained companion before native load, reuse or resume."""
    reference = binding(ref.metadata)
    if reference is None:
        return
    tree = primary
    for _ in PurePosixPath(str(reference["primary"])).parts:
        tree = tree.parent
    if contained(tree, str(reference["primary"])) != primary:
        raise ArtifactStoreError("shared artifact primary binding conflicts")
    read_receipt(tree, reference)


def publication_path_is_retained(path: Path) -> bool:
    """Retain native publication receipts, staging and their complete trees.

    There is no implicit expiry or unpin operation. Native authority/reference
    settlement must precede a future explicit reclamation policy.
    """
    target = path.absolute()
    try:
        for ancestor in (target, *target.parents):
            receipt = ancestor / RECEIPT
            if receipt.exists() or receipt.is_symlink():
                return True
        def unreadable(error: OSError) -> None:
            raise error
        if target.is_dir():
            for _, names, files in os.walk(target, followlinks=False, onerror=unreadable):
                if RECEIPT in names or RECEIPT in files:
                    return True
        return False
    except OSError:
        return True
