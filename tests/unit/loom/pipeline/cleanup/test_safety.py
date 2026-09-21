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


def test_preparation_pins_protect_evidence_without_rewriting_the_run(tmp_path) -> None:
    from loom.pipeline.cleanup.preparation_pins import retain_preparation_path

    run = tmp_path / "runs" / "prepared"
    artifact = run / "artifacts" / "report.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{}")
    before = (artifact.read_bytes(), artifact.stat().st_mtime_ns)
    retain_preparation_path(
        run, coordinator_id="coordinator-1", operation_id="prepare-1"
    )
    pins = tuple((tmp_path / "runs" / ".loom-preparation-pins").rglob("*.json"))
    assert len(pins) == 1
    pin_before = (pins[0].read_bytes(), pins[0].stat().st_mtime_ns)
    retain_preparation_path(
        run, coordinator_id="coordinator-1", operation_id="prepare-1"
    )
    assert (pins[0].read_bytes(), pins[0].stat().st_mtime_ns) == pin_before
    assert (artifact.read_bytes(), artifact.stat().st_mtime_ns) == before
    for target in (artifact, run, run.parent, pins[0]):
        decision = assess_local_target_safety(_target(target), (_root(tmp_path),))
        assert decision.reason_code is CleanupSafetyReason.RETAINED_PREPARATION_EVIDENCE
    sibling = tmp_path / "runs" / "unrelated.txt"
    sibling.write_text("unrelated")
    assert assess_local_target_safety(_target(sibling), (_root(tmp_path),)).approved


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


@pytest.mark.parametrize("published", [False, True])
def test_shared_attempt_and_committed_closure_are_retained(tmp_path, published):
    from tests.unit.loom.queue.test_remote_stage_execution import _shared_publication_workspace
    from loom.queue._shared_publication import publish
    from pathlib import Path
    workspace, profile, _, result = _shared_publication_workspace(tmp_path)
    if published:
        ref = publish(workspace.request(), workspace.retain_outputs(), profile.shared_roots,
                      agent_id="agent-1", fence="fence-1")["result"]
    else:
        # Worker completion is not publication or authority settlement.
        ref = result.outputs["result"]
    primary = Path(ref.uri.removeprefix("file://"))
    for target in (primary, primary.parent, tmp_path / "shared"):
        decision = assess_local_target_safety(_target(target), (_root(tmp_path),))
        assert not decision.approved
        assert decision.reason_code is CleanupSafetyReason.RETAINED_SHARED_PUBLICATION
        assert primary.is_file()


def test_action_candidate_verification_retains_and_checks_shared_companions(tmp_path):
    from pathlib import Path
    import pytest
    from loom.queue._action_result_resolution import ActionResultResolution
    from loom.queue._shared_publication import publish
    from loom.pipeline.stores.errors import ArtifactStoreError
    from tests.unit.loom.queue.test_remote_stage_execution import _shared_publication_workspace

    workspace, profile, _, _ = _shared_publication_workspace(tmp_path)
    reference = publish(workspace.request(), workspace.retain_outputs(), profile.shared_roots, agent_id="agent-1", fence="fence-1")["result"]
    verifier = object.__new__(ActionResultResolution)
    verifier._verify_artifact(reference)
    primary = Path(reference.uri.removeprefix("file://"))
    for path in (primary, primary.parent / "values.bin", primary.parent / "catalog" / "checkpoint"):
        assert assess_local_target_safety(_target(path), (_root(tmp_path),)).reason_code is CleanupSafetyReason.RETAINED_SHARED_PUBLICATION
    (primary.parent / "catalog" / "checkpoint").write_bytes(b"corrupt companion")
    with pytest.raises(ArtifactStoreError, match="closure integrity"):
        verifier._verify_artifact(reference)
