"""Unit tests for lifecycle status helpers."""

from pathlib import Path

import pytest

from loom.pipeline.execution.lifecycle import write_stage_blocked
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import LocalRunStore, path_to_run_uri


def _run_uri(tmp_path: Path) -> str:
    return path_to_run_uri(tmp_path / "runs" / "run1")


def test_write_stage_blocked_writes_status_only(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)

    record = write_stage_blocked(
        store,
        run_uri=run_uri,
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
    assert store.read_stage_status(run_uri, "downstream") == record

    stage_dir = store.local_stage_dir(run_uri, "downstream")
    assert sorted(path.name for path in stage_dir.iterdir()) == ["status.json"]
    assert store.read_stage_inputs(run_uri, "downstream") is None
    assert store.read_stage_outputs(run_uri, "downstream") is None
    assert store.read_stage_fingerprint(run_uri, "downstream") is None
    assert store.read_stage_failure(run_uri, "downstream") is None
    assert store.read_stage_provenance(run_uri, "downstream") is None
    assert not (stage_dir / "logs").exists()
    assert sorted(path.name for path in stage_dir.iterdir()) == ["status.json"]


def test_write_stage_blocked_requires_message_and_reason_code_when_present(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)

    with pytest.raises(ValueError, match="message"):
        write_stage_blocked(
            store,
            run_uri=run_uri,
            stage_name="downstream",
            attempt=1,
            blocked_at="2020-01-01T00:00:00Z",
            message="",
        )

    with pytest.raises(ValueError, match="reason_code"):
        write_stage_blocked(
            store,
            run_uri=run_uri,
            stage_name="downstream",
            attempt=1,
            blocked_at="2020-01-01T00:00:00Z",
            message="blocked",
            reason_code="",
        )
