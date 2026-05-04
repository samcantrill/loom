"""Unit tests for lifecycle status helpers."""

from pathlib import Path

import pytest

from loom.pipeline.execution.lifecycle import write_stage_blocked
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import LocalRunStore


def test_write_stage_blocked_writes_status_only(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    store.create_run("run1")

    record = write_stage_blocked(
        store,
        run_id="run1",
        stage_name="downstream",
        attempt=1,
        blocked_at="2020-01-01T00:00:00Z",
        message="upstream failed",
        blocked_by=["upstream"],
        reason_code="upstream_failed",
        metadata={"reason_details": {"exit_code": 2}},
    )

    assert record.status is StageStatus.BLOCKED
    assert record.started_at is None
    assert record.finished_at is None
    assert record.owner == {}
    assert record.metadata == {
        "blocked_by": ["upstream"],
        "reason_code": "upstream_failed",
        "reason_details": {"exit_code": 2},
    }
    assert store.read_stage_status("run1", "downstream") == record

    stage_dir = store.local_stage_dir("run1", "downstream")
    assert sorted(path.name for path in stage_dir.iterdir()) == ["status.json"]
    assert store.read_stage_inputs("run1", "downstream") is None
    assert store.read_stage_outputs("run1", "downstream") is None
    assert store.read_stage_fingerprint("run1", "downstream") is None
    assert store.read_stage_failure("run1", "downstream") is None
    assert store.read_stage_provenance("run1", "downstream") is None
    assert not (stage_dir / "logs").exists()
    assert sorted(path.name for path in stage_dir.iterdir()) == ["status.json"]


def test_write_stage_blocked_requires_message_and_reason_code_when_present(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    store.create_run("run1")

    with pytest.raises(ValueError, match="message"):
        write_stage_blocked(
            store,
            run_id="run1",
            stage_name="downstream",
            attempt=1,
            blocked_at="2020-01-01T00:00:00Z",
            message="",
        )

    with pytest.raises(ValueError, match="reason_code"):
        write_stage_blocked(
            store,
            run_id="run1",
            stage_name="downstream",
            attempt=1,
            blocked_at="2020-01-01T00:00:00Z",
            message="blocked",
            reason_code="",
        )
