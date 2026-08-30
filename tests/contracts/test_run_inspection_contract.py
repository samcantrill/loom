from __future__ import annotations

from pathlib import Path

import pytest

from loom.diagnostics import (
    RunInspectionAxis,
    RunInspectionAxisName,
    RunInspectionResult,
    RunInspectionTruncation,
    decode_run_inspection_response,
)
from loom.queue import (
    LocalDaemonSocketClient,
    LocalDaemonSocketServer,
    QueueEnqueueRequest,
    QueueService,
    QueueStorageError,
    SQLiteQueueRepository,
    normalize_queue_spec,
)


class _SocketViews:
    def client_view(self, principal: object) -> object:
        return object()

    def operator_view(self, principal: object) -> object:
        return object()


def test_direct_and_unix_sources_share_the_exact_v1_model(tmp_path: Path) -> None:
    direct = RunInspectionResult(
        run_uri="file:///runs/contract",
        as_of="2026-08-30T00:00:00Z",
        summary="RUNNING",
        queue_item_id="queue-contract",
        admission_id="admission-contract",
        axes=_all_axes(
            RunInspectionAxis(
                RunInspectionAxisName.LIFECYCLE,
                "authority",
                "available",
                "RUNNING",
                7,
                "2026-08-30T00:00:00Z",
                "current",
            ),
        ),
        stages=(),
        locations=(),
        truncation=(
            RunInspectionTruncation("stages", 0, 0),
            RunInspectionTruncation("locations", 0, 0),
        ),
    )
    endpoint = tmp_path / "inspection.sock"
    server = LocalDaemonSocketServer(
        _SocketViews(),  # type: ignore[arg-type]
        endpoint,
        inspect_run=lambda run_uri: direct.to_dict(),
    )
    server.start()
    try:
        unix = decode_run_inspection_response(
            LocalDaemonSocketClient(endpoint).inspect_run(direct.run_uri)
        )
    finally:
        server.stop()

    assert unix == direct
    assert unix.to_dict() == direct.to_dict()
    assert set(direct.to_dict()) == {
        "schema_version",
        "run_uri",
        "as_of",
        "summary",
        "queue_item_id",
        "admission_id",
        "axes",
        "stages",
        "locations",
        "truncation",
    }


def test_existing_queue_can_be_read_exactly_without_writes(tmp_path: Path) -> None:
    database = tmp_path / "queue.sqlite"
    spec = normalize_queue_spec(
        {
            "schema_version": 2,
            "db_path": str(database),
            "pools": [{"pool_name": "pool", "mode": "delegated"}],
            "queues": [{"queue_name": "queue", "pool_name": "pool"}],
        }
    )
    service = QueueService.from_spec(spec)
    service.start()
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="item-1",
            queue_name="queue",
            run_uri="file:///runs/item-1",
        )
    )
    before = database.read_bytes()

    reader = SQLiteQueueRepository.open_read_only(database)
    item = reader.read_item("item-1")

    assert item is not None and item.run_uri == "file:///runs/item-1"
    assert database.read_bytes() == before


def test_read_only_queue_open_does_not_create_a_missing_database(
    tmp_path: Path,
) -> None:
    database = tmp_path / "missing.sqlite"

    with pytest.raises(QueueStorageError, match="does not exist"):
        SQLiteQueueRepository.open_read_only(database)

    assert not database.exists()


def _all_axes(*overrides: RunInspectionAxis) -> tuple[RunInspectionAxis, ...]:
    selected = {axis.name: axis for axis in overrides}
    return tuple(
        selected.get(
            name,
            RunInspectionAxis(
                name,
                "unavailable",
                "unavailable",
                "unavailable",
                None,
                None,
                "unavailable",
                "owner_unavailable",
            ),
        )
        for name in RunInspectionAxisName
    )
