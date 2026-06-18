"""Unit tests for cleanup safety decisions."""

from __future__ import annotations

from typing import cast

import pytest

from loom.serialization import PlainData
from loom.pipeline.cleanup import (
    CleanupManagedRoot,
    CleanupSafetyReason,
    CleanupSafetyStatus,
    CleanupTargetKind,
    CleanupTargetRef,
    assess_local_target_safety,
)


pytestmark = pytest.mark.unit


def _root(path: object) -> CleanupManagedRoot:
    return CleanupManagedRoot(
        root_id="root-1",
        uri=str(path),
        ownership_key="run-1",
        metadata={"owned_by": "loom"},
    )


def _target(path: object, **metadata: object) -> CleanupTargetRef:
    return CleanupTargetRef(
        kind=CleanupTargetKind.LOCAL_PATH,
        uri=str(path),
        ownership_key="run-1",
        metadata=cast(dict[str, PlainData], metadata),
    )


def test_safety_approves_owned_target_under_managed_root(tmp_path) -> None:
    target_path = tmp_path / "payload.txt"
    target_path.write_text("payload")

    decision = assess_local_target_safety(_target(target_path), (_root(tmp_path),))

    assert decision.status is CleanupSafetyStatus.APPROVED
    assert decision.reason_code is CleanupSafetyReason.APPROVED
    assert decision.approved is True
    assert decision.managed_root_id == "root-1"


def test_safety_rejects_target_outside_managed_root(tmp_path) -> None:
    outside = tmp_path.parent / "outside-payload.txt"
    outside.write_text("payload")

    decision = assess_local_target_safety(_target(outside), (_root(tmp_path),))

    assert decision.status is CleanupSafetyStatus.REJECTED
    assert decision.reason_code is CleanupSafetyReason.OUTSIDE_MANAGED_ROOT


def test_safety_rejects_missing_ownership_evidence(tmp_path) -> None:
    target_path = tmp_path / "payload.txt"
    target_path.write_text("payload")
    target = CleanupTargetRef(kind=CleanupTargetKind.LOCAL_PATH, uri=str(target_path))
    root = CleanupManagedRoot(root_id="root-1", uri=str(tmp_path))

    decision = assess_local_target_safety(target, (root,))

    assert decision.status is CleanupSafetyStatus.REJECTED
    assert decision.reason_code is CleanupSafetyReason.MISSING_OWNERSHIP_EVIDENCE


def test_safety_rejects_symlink_target(tmp_path) -> None:
    actual = tmp_path / "actual.txt"
    actual.write_text("payload")
    link = tmp_path / "link.txt"
    link.symlink_to(actual)

    decision = assess_local_target_safety(_target(link), (_root(tmp_path),))

    assert decision.status is CleanupSafetyStatus.REJECTED
    assert decision.reason_code is CleanupSafetyReason.TARGET_IS_SYMLINK


def test_safety_rejects_symlink_component(tmp_path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "payload.txt").write_text("payload")
    root = tmp_path / "root"
    root.mkdir()
    link = root / "link"
    link.symlink_to(outside, target_is_directory=True)

    decision = assess_local_target_safety(
        _target(link / "payload.txt"),
        (_root(root),),
    )

    assert decision.status is CleanupSafetyStatus.REJECTED
    assert decision.reason_code is CleanupSafetyReason.SYMLINK_COMPONENT_NOT_ALLOWED


def test_safety_reports_unsupported_remote_ref() -> None:
    target = CleanupTargetRef(
        kind=CleanupTargetKind.REMOTE_REF,
        uri="s3://bucket/key",
        metadata={"loom_owned": True},
    )

    decision = assess_local_target_safety(target, ())

    assert decision.status is CleanupSafetyStatus.REJECTED
    assert decision.reason_code is CleanupSafetyReason.UNSUPPORTED_TARGET_KIND
