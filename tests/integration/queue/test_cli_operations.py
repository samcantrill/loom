"""Integration coverage for queue CLI-backed operations."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from loom.cli.main import main
from loom.cli.queue import (
    build_queue_cancel_result,
    build_queue_drain_result,
    build_queue_preflight_result,
    build_queue_status_result,
)
from loom.queue import (
    LocalDaemonSocketClient,
    ManagedRecoveryTarget,
    QueueEnqueueRequest,
    QueueItemStatus,
    QueueService,
    RecoverUnknownAssignment,
    load_queue_spec,
)


pytestmark = pytest.mark.optional_dependency


def test_queue_cli_builders_operate_against_sqlite_service(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    config_path = _queue_config(tmp_path)
    _enqueue(config_path, "item-1")

    preflight = build_queue_preflight_result(config_path)
    before = build_queue_status_result(config_path, queue_item_id="item-1")
    drain = build_queue_drain_result(config_path, max_items=1)
    after = build_queue_status_result(config_path, queue_item_id="item-1")

    assert preflight.ok
    assert before.item_inspection is not None
    assert before.item_inspection.item is not None
    assert before.item_inspection.item.status is QueueItemStatus.QUEUED
    assert len(drain.steps) == 1
    assert after.item_inspection is not None
    assert after.item_inspection.item is not None
    assert after.item_inspection.item.status is QueueItemStatus.SUCCEEDED


def test_queue_cli_cancel_builder_records_cancellation(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    config_path = _queue_config(tmp_path)
    _enqueue(config_path, "item-1")

    result = build_queue_cancel_result(
        config_path,
        "item-1",
        requested_by="integration",
        reason="not-needed",
    )

    assert result.item.status is QueueItemStatus.CANCELLED
    assert result.item.cancellation is not None
    assert result.item.cancellation.requested_by == "integration"


def test_guarded_recovery_cli_parses_the_exact_request_and_delegates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = RecoverUnknownAssignment(
        recovery_id="recover-from-cli",
        run_uri="file:///run",
        stage_name="train",
        attempt=1,
        stage_work_id="work-1",
        assignment_id="assignment-1",
        process_execution_id="process-1",
        execution_fence="fence-1",
        target=ManagedRecoveryTarget("agent-a", "session-a"),
        expected_state_version=7,
        requested_outcome="failed",
        consider_retry=True,
        reason="operator verified containment",
    )
    request_path = tmp_path / "recovery.json"
    request_path.write_text(json.dumps(request.to_dict()), encoding="utf-8")
    received: list[RecoverUnknownAssignment] = []

    def recover_unknown(
        _client: LocalDaemonSocketClient, candidate: RecoverUnknownAssignment
    ) -> dict[str, object]:
        received.append(candidate)
        return {
            "recovery_id": candidate.recovery_id,
            "state": "closed",
            "evidence": "TEST_CONTAINMENT",
        }

    monkeypatch.setattr(LocalDaemonSocketClient, "recover_unknown", recover_unknown)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "queue",
                "daemon-recover-unknown",
                "--endpoint",
                str(tmp_path / "daemon.sock"),
                "--request",
                str(request_path),
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    assert stderr.getvalue() == ""
    assert received == [request]
    envelope = json.loads(stdout.getvalue())
    assert envelope["result"]["recovery_id"] == request.recovery_id
    assert envelope["result"]["state"] == "closed"


def _queue_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "queue.yaml"
    config_path.write_text(
        f"""
        queue:
          service:
            db_path: {tmp_path / "queue.sqlite"}
          pools:
            - pool_name: gpu-pool
              mode: managed
          queues:
            - queue_name: gpu
              pool_name: gpu-pool
        """,
        encoding="utf-8",
    )
    return config_path


def _enqueue(config_path: Path, queue_item_id: str) -> None:
    service = QueueService.from_spec(
        load_queue_spec(config_path),
        clock=_clock("2020-01-01T00:00:00Z"),
    )
    service.start()
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id=queue_item_id,
            queue_name="gpu",
            run_uri=f"file:///runs/{queue_item_id}",
        )
    )


def _clock(*values: str):
    remaining = list(values)

    def next_value() -> str:
        if len(remaining) == 1:
            return remaining[0]
        return remaining.pop(0)

    return next_value
