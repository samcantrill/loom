"""Cleanup target safety decisions."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import cast
from urllib.parse import unquote, urlparse

from loom.pipeline.cleanup.errors import CleanupSafetyError
from loom.pipeline.cleanup.records import (
    CleanupManagedRoot,
    CleanupTargetKind,
    CleanupTargetRef,
)
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data

CLEANUP_SAFETY_SCHEMA_VERSION = 1


class CleanupSafetyStatus(StrEnum):
    """Safety decision status values."""

    APPROVED = "approved"
    SKIPPED = "skipped"
    REJECTED = "rejected"


class CleanupSafetyReason(StrEnum):
    """Stable cleanup safety reason codes."""

    APPROVED = "approved"
    TARGET_MISSING = "target_missing"
    UNSUPPORTED_TARGET_KIND = "unsupported_target_kind"
    UNSUPPORTED_URI_SCHEME = "unsupported_uri_scheme"
    NO_MANAGED_ROOT = "no_managed_root"
    OUTSIDE_MANAGED_ROOT = "outside_managed_root"
    MISSING_OWNERSHIP_EVIDENCE = "missing_ownership_evidence"
    TARGET_IS_SYMLINK = "target_is_symlink"
    SYMLINK_COMPONENT_NOT_ALLOWED = "symlink_component_not_allowed"


@dataclass(frozen=True, slots=True)
class CleanupSafetyDecision:
    """Decision returned by cleanup safety checks."""

    target: CleanupTargetRef
    status: CleanupSafetyStatus
    reason_code: CleanupSafetyReason
    schema_version: int = CLEANUP_SAFETY_SCHEMA_VERSION
    managed_root_id: str | None = None
    message: str | None = None
    detail: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_schema_version(self.schema_version, "schema_version"),
        )
        if not isinstance(self.target, CleanupTargetRef):
            raise CleanupSafetyError("target must be a CleanupTargetRef")
        object.__setattr__(self, "status", _status(self.status))
        object.__setattr__(self, "reason_code", _reason(self.reason_code))
        object.__setattr__(
            self,
            "managed_root_id",
            _optional_string(self.managed_root_id, "managed_root_id"),
        )
        object.__setattr__(self, "message", _optional_string(self.message, "message"))
        object.__setattr__(self, "detail", _plain_mapping(self.detail, "detail"))

    @property
    def approved(self) -> bool:
        return self.status is CleanupSafetyStatus.APPROVED

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "target": self.target.to_dict(),
            "status": self.status.value,
            "reason_code": self.reason_code.value,
            "managed_root_id": self.managed_root_id,
            "message": self.message,
            "detail": thaw_plain_data(self.detail, path="detail"),
        }


def assess_local_target_safety(
    target: CleanupTargetRef,
    managed_roots: Iterable[CleanupManagedRoot],
    *,
    require_ownership: bool = True,
) -> CleanupSafetyDecision:
    """Assess whether a local cleanup target is safe to delete later."""

    if not isinstance(target, CleanupTargetRef):
        raise CleanupSafetyError("target must be a CleanupTargetRef")
    if target.kind is not CleanupTargetKind.LOCAL_PATH:
        return _decision(
            target,
            CleanupSafetyStatus.REJECTED,
            CleanupSafetyReason.UNSUPPORTED_TARGET_KIND,
            "only local path targets are supported in Stage 21",
        )
    target_path = _local_path_from_uri(target.uri, target=target)
    if target_path is None:
        return _decision(
            target,
            CleanupSafetyStatus.REJECTED,
            CleanupSafetyReason.UNSUPPORTED_URI_SCHEME,
            "target is not a supported local path URI",
        )
    roots = tuple(managed_roots)
    if not roots:
        return _decision(
            target,
            CleanupSafetyStatus.REJECTED,
            CleanupSafetyReason.NO_MANAGED_ROOT,
            "no trusted managed root was provided",
        )
    root_match = _matching_root(target_path, roots)
    if root_match is None:
        return _decision(
            target,
            CleanupSafetyStatus.REJECTED,
            CleanupSafetyReason.OUTSIDE_MANAGED_ROOT,
            "target is outside trusted managed roots",
            detail={"path": str(target_path)},
        )
    root, root_path = root_match
    if require_ownership and not _has_ownership_evidence(target, root):
        return _decision(
            target,
            CleanupSafetyStatus.REJECTED,
            CleanupSafetyReason.MISSING_OWNERSHIP_EVIDENCE,
            "target lacks cleanup ownership evidence",
            managed_root_id=root.root_id,
        )
    symlink_component = _first_symlink_component(target_path, root_path)
    if symlink_component is not None and symlink_component != target_path:
        return _decision(
            target,
            CleanupSafetyStatus.REJECTED,
            CleanupSafetyReason.SYMLINK_COMPONENT_NOT_ALLOWED,
            "target path crosses a symlink component",
            managed_root_id=root.root_id,
            detail={"symlink": str(symlink_component)},
        )
    if target_path.is_symlink():
        return _decision(
            target,
            CleanupSafetyStatus.REJECTED,
            CleanupSafetyReason.TARGET_IS_SYMLINK,
            "target is a symlink",
            managed_root_id=root.root_id,
            detail={"path": str(target_path)},
        )
    if not target_path.exists():
        return _decision(
            target,
            CleanupSafetyStatus.SKIPPED,
            CleanupSafetyReason.TARGET_MISSING,
            "target does not exist",
            managed_root_id=root.root_id,
            detail={"path": str(target_path)},
        )
    return _decision(
        target,
        CleanupSafetyStatus.APPROVED,
        CleanupSafetyReason.APPROVED,
        "target is under a trusted managed root and has ownership evidence",
        managed_root_id=root.root_id,
        detail={"path": str(target_path)},
    )


def _decision(
    target: CleanupTargetRef,
    status: CleanupSafetyStatus,
    reason_code: CleanupSafetyReason,
    message: str,
    *,
    managed_root_id: str | None = None,
    detail: Mapping[str, PlainData] | None = None,
) -> CleanupSafetyDecision:
    return CleanupSafetyDecision(
        target=target,
        status=status,
        reason_code=reason_code,
        managed_root_id=managed_root_id,
        message=message,
        detail={} if detail is None else detail,
    )


def _local_path_from_uri(uri: str, *, target: CleanupTargetRef) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme in ("", "file"):
        if parsed.scheme == "file" and parsed.netloc not in ("", "localhost"):
            return None
        raw_path = unquote(parsed.path if parsed.scheme == "file" else uri)
        if not raw_path:
            return None
        return Path(os.path.abspath(raw_path))
    if target.kind is CleanupTargetKind.LOCAL_PATH:
        return None
    return None


def _matching_root(
    target_path: Path, roots: tuple[CleanupManagedRoot, ...]
) -> tuple[CleanupManagedRoot, Path] | None:
    for root in roots:
        root_path = _root_path(root)
        if root_path is None:
            continue
        try:
            target_path.relative_to(root_path)
        except ValueError:
            continue
        return root, root_path
    return None


def _root_path(root: CleanupManagedRoot) -> Path | None:
    parsed = urlparse(root.uri)
    if parsed.scheme not in ("", "file"):
        return None
    if parsed.scheme == "file" and parsed.netloc not in ("", "localhost"):
        return None
    raw_path = unquote(parsed.path if parsed.scheme == "file" else root.uri)
    if not raw_path:
        return None
    return Path(os.path.abspath(raw_path))


def _has_ownership_evidence(
    target: CleanupTargetRef, root: CleanupManagedRoot
) -> bool:
    if target.ownership_key is not None and target.ownership_key == root.ownership_key:
        return True
    for mapping in (target.metadata, root.metadata):
        if mapping.get("loom_owned") is True:
            return True
        if mapping.get("owned_by") == "loom":
            return True
        if mapping.get("ownership") == "loom":
            return True
    return False


def _first_symlink_component(target_path: Path, root_path: Path) -> Path | None:
    try:
        relative = target_path.relative_to(root_path)
    except ValueError:
        return None
    current = root_path
    if current.is_symlink():
        return current
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return current
    return None


def _require_schema_version(value: object, field: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value != CLEANUP_SAFETY_SCHEMA_VERSION
    ):
        raise CleanupSafetyError(f"{field} must be {CLEANUP_SAFETY_SCHEMA_VERSION}")
    return value


def _status(value: object) -> CleanupSafetyStatus:
    if isinstance(value, CleanupSafetyStatus):
        return value
    if isinstance(value, str):
        try:
            return CleanupSafetyStatus(value)
        except ValueError as exc:
            raise CleanupSafetyError(
                "status must be one of: approved, skipped, rejected"
            ) from exc
    raise CleanupSafetyError("status must be one of: approved, skipped, rejected")


def _reason(value: object) -> CleanupSafetyReason:
    if isinstance(value, CleanupSafetyReason):
        return value
    if isinstance(value, str):
        try:
            return CleanupSafetyReason(value)
        except ValueError as exc:
            raise CleanupSafetyError("reason_code is not supported") from exc
    raise CleanupSafetyError("reason_code is not supported")


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise CleanupSafetyError(f"{field} must be a non-empty string or None")
    return value


def _plain_mapping(value: object, field: str) -> Mapping[str, PlainData]:
    if not isinstance(value, Mapping):
        raise CleanupSafetyError(f"{field} must be a mapping")
    try:
        return cast(Mapping[str, PlainData], freeze_plain_data(value, path=field))
    except Exception as exc:
        raise CleanupSafetyError(f"{field} must contain plain data") from exc


__all__ = [
    "CLEANUP_SAFETY_SCHEMA_VERSION",
    "CleanupSafetyDecision",
    "CleanupSafetyReason",
    "CleanupSafetyStatus",
    "assess_local_target_safety",
]
