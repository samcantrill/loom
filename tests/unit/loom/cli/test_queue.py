"""Unit coverage for the queue CLI wrapper."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from loom.cli.main import main
from loom.queue import QueueEnqueueRequest, QueueService, load_queue_spec


pytestmark = pytest.mark.unit


def test_queue_status_json_reports_item_and_ownership(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    config_path = _queue_config(tmp_path)
    _enqueue(config_path, "item-1")
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        [
            "queue",
            "status",
            str(config_path),
            "--item",
            "item-1",
            "--format",
            "json",
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == "loom.cli.queue.status.v1"
    assert payload["ok"] is True
    assert payload["result"]["item"]["item"]["queue_item_id"] == "item-1"
    assert "authority remains" in payload["result"]["ownership"]["authority_state"]


def test_queue_cancel_records_queue_local_cancellation(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    config_path = _queue_config(tmp_path)
    _enqueue(config_path, "item-1")
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        [
            "queue",
            "cancel",
            str(config_path),
            "item-1",
            "--reason",
            "operator-requested",
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert "queue cancel item-1: CANCELLED" in stdout.getvalue()
    assert "operator-requested" in stdout.getvalue()


def test_queue_drain_foreground_dispatches_fake_item(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    config_path = _queue_config(tmp_path)
    _enqueue(config_path, "item-1")
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        [
            "queue",
            "drain-foreground",
            str(config_path),
            "--max-items",
            "1",
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert "queue drain foreground: 1 step(s)" in stdout.getvalue()
    assert "dispatched: item-1 SUCCEEDED" in stdout.getvalue()


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
        clock=_clock(
            "2020-01-01T00:00:00Z",
            "2020-01-01T00:00:01Z",
            "2020-01-01T00:00:02Z",
            "2020-01-01T00:00:03Z",
        ),
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
