"""Unit coverage for queue operational status read models."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from loom.cli.formatting import format_queue_status_text
from loom.queue import (
    DispatchHandle,
    QueueEnqueueRequest,
    QueueItem,
    QueueItemStatus,
    QueueService,
    normalize_queue_spec,
)
from loom.queue.controller import (
    QueueDispatchInspection,
    QueueDispatchResult,
    QueueInspectableDispatchAdapter,
)
from loom.queue.status import build_queue_operational_status, build_queue_pool_status


pytestmark = pytest.mark.unit


def test_queue_operational_status_keeps_ownership_sections_separate(
    tmp_path: Path,
) -> None:
    service = QueueService.from_spec(
        normalize_queue_spec(
            {
                "db_path": str(tmp_path / "queue.sqlite"),
                "pools": [{"pool_name": "gpu-pool", "mode": "managed"}],
                "queues": [{"queue_name": "gpu", "pool_name": "gpu-pool"}],
            }
        ),
        clock=_clock("2020-01-01T00:00:00Z"),
    )
    service.start()
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="item-1",
            queue_name="gpu",
            run_uri="file:///runs/item-1",
        )
    )

    report = build_queue_operational_status(service, queue_item_id="item-1")
    payload = report.to_dict()
    item = cast(Mapping[str, object], payload["item"])
    item_payload = cast(Mapping[str, object], item["item"])
    ownership = cast(Mapping[str, str], payload["ownership"])

    assert payload["service_scope"] == "in_process_command"
    assert item_payload["status"] == QueueItemStatus.QUEUED.value
    assert ownership["queue_state"].startswith("queue service owns")
    assert "authority remains" in ownership["authority_state"]
    assert "delegated adapters" in ownership["delegated_scheduler_state"]


def test_pool_status_has_exact_allowlisted_shape_and_never_reads_legacy_evidence(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="active",
            queue_name="gpu",
            run_uri="file:///runs/active",
            adapter="local",
        )
    )
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="queued", queue_name="gpu", run_uri="file:///runs/queued"
        )
    )
    claimed = service.claim_next(
        "gpu-pool", owner_id="controller", claim_id="claim-1"
    )
    assert claimed is not None
    active = service.record_dispatch_handle(
        "active",
        DispatchHandle(
            adapter="local",
            handle_id="handle-1",
            dispatched_at="2020-01-01T00:00:01Z",
            dispatch_attempt=1,
            evidence={
                "managed_local": {
                    "schema_version": 1,
                    "owner_id": "controller",
                    "session_id": "session-1",
                    "pid": 101,
                    "pgid": 101,
                    "assignment": {
                        "provider_name": "static-slots",
                        "slots": [
                            {
                                "resource_name": "gpu",
                                "slot_id": "slot-a",
                                "label": "A",
                                "lease_id": "lease-1",
                                "expires_at": "2020-01-01T00:01:00Z",
                                "secret_value": "do-not-render",
                            }
                        ],
                    },
                    "logs": {
                        "stdout_path": "logs/active.stdout.log",
                        "stderr_path": "logs/active.stderr.log",
                    },
                    "command": "do-not-render",
                },
                "fencing_token": "do-not-render",
            },
        ),
        expected=claimed.item,
    )
    assert active.status is QueueItemStatus.DISPATCHED

    pool = build_queue_pool_status(service, pool_name="gpu-pool").to_dict()

    assert set(pool) == {
        "pool_name",
        "controller_max_active_items",
        "counts",
        "active_attempts",
    }
    assert pool["counts"] == {
        "queued": 1,
        "claimed": 0,
        "dispatched": 1,
        "active": 1,
        "succeeded": 0,
        "failed": 0,
        "cancelled": 0,
        "unknown": 0,
    }
    attempts = cast(list[object], pool["active_attempts"])
    attempt = cast(Mapping[str, object], attempts[0])
    assert set(attempt) == {
        "queue_item_id",
        "status",
        "owner_id",
        "session_id",
        "evidence_source",
        "live_observation",
        "process",
        "assignment",
        "logs",
    }
    assert attempt["evidence_source"] == "persisted"
    assert attempt["live_observation"] == "not_requested"
    rendered = str(pool)
    assert "do-not-render" not in rendered
    assert "fencing_token" not in rendered
    assert "secret_value" not in rendered


def test_pool_status_claimed_item_has_no_fabricated_handle_facts(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="claimed", queue_name="gpu", run_uri="file:///runs/claimed"
        )
    )
    assert service.claim_next("gpu-pool", owner_id="controller", claim_id="claim-1")

    pool = build_queue_pool_status(service, pool_name="gpu-pool").to_dict()
    attempt = cast(Mapping[str, object], cast(list[object], pool["active_attempts"])[0])

    assert attempt["owner_id"] == "controller"
    assert attempt["session_id"] is None
    assert attempt["process"] is None
    assert attempt["assignment"] is None
    assert attempt["logs"] is None


def test_pool_status_is_additive_only_when_pool_requested(tmp_path: Path) -> None:
    service = _service(tmp_path)

    legacy = build_queue_operational_status(service).to_dict()
    selected = build_queue_operational_status(
        service, pool_name="gpu-pool"
    ).to_dict()

    assert "pool" not in legacy
    assert set(selected) == set(legacy) | {"pool"}


def test_pool_status_labels_only_matching_same_session_observation(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="active",
            queue_name="gpu",
            run_uri="file:///runs/active",
            adapter="local",
        )
    )
    claimed = service.claim_next("gpu-pool", owner_id="controller", claim_id="claim")
    assert claimed is not None
    service.record_dispatch_handle(
        "active",
        _managed_handle(),
        expected=claimed.item,
    )

    matching_pool = build_queue_pool_status(
        service,
        pool_name="gpu-pool",
        adapters=cast(
            Mapping[str, QueueInspectableDispatchAdapter],
            {"local": _InspectableAdapter("controller", "session-1", "handle-1")},
        ),
    ).to_dict()
    mismatch_pool = build_queue_pool_status(
        service,
        pool_name="gpu-pool",
        adapters=cast(
            Mapping[str, QueueInspectableDispatchAdapter],
            {"local": _InspectableAdapter("controller", "other", "handle-1")},
        ),
    ).to_dict()
    matching = cast(
        Mapping[str, object],
        cast(list[object], matching_pool["active_attempts"])[0],
    )
    mismatch = cast(
        Mapping[str, object],
        cast(list[object], mismatch_pool["active_attempts"])[0],
    )

    assert matching["evidence_source"] == "same_session_live"
    assert matching["live_observation"] == "same_session"
    assert mismatch["evidence_source"] == "persisted"
    assert mismatch["live_observation"] == "unavailable"


def test_pool_status_text_matches_json_safe_facts_and_redaction(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="active",
            queue_name="gpu",
            run_uri="file:///runs/active",
            adapter="local",
        )
    )
    claimed = service.claim_next("gpu-pool", owner_id="controller", claim_id="claim")
    assert claimed is not None
    service.record_dispatch_handle("active", _managed_handle(), expected=claimed.item)

    report = build_queue_operational_status(service, pool_name="gpu-pool")
    payload = report.to_dict()
    attempt = cast(
        Mapping[str, object],
        cast(list[object], cast(Mapping[str, object], payload["pool"])["active_attempts"])[0],
    )
    text = format_queue_status_text(report)

    for value in (
        payload["pool"]["pool_name"],
        attempt["queue_item_id"],
        attempt["owner_id"],
        attempt["session_id"],
        attempt["evidence_source"],
        attempt["live_observation"],
        "101",
        "static-slots",
        "slot-a",
        "lease-1",
        "logs/active.stdout.log",
        "logs/active.stderr.log",
    ):
        assert str(value) in text
    assert "argv" not in text
    assert "fencing_token" not in text


def _managed_handle() -> DispatchHandle:
    return DispatchHandle(
        adapter="local",
        handle_id="handle-1",
        dispatched_at="2020-01-01T00:00:01Z",
        dispatch_attempt=1,
        evidence={
            "managed_local": {
                "schema_version": 1,
                "owner_id": "controller",
                "session_id": "session-1",
                "pid": 101,
                "pgid": 101,
                "assignment": {
                    "provider_name": "static-slots",
                    "slots": [
                        {
                            "resource_name": "gpu",
                            "slot_id": "slot-a",
                            "label": "A",
                            "lease_id": "lease-1",
                            "expires_at": "2020-01-01T00:01:00Z",
                        }
                    ],
                },
                "logs": {
                    "stdout_path": "logs/active.stdout.log",
                    "stderr_path": "logs/active.stderr.log",
                },
            }
        },
    )


class _InspectableAdapter:
    adapter_name = "local"

    def __init__(self, owner_id: str, session_id: str, handle_id: str) -> None:
        self.owner_id = owner_id
        self.session_id = session_id
        self._handle_id = handle_id

    def inspect(self, _item: QueueItem) -> QueueDispatchInspection:
        return QueueDispatchInspection(
            status=QueueItemStatus.DISPATCHED,
            reason="active",
            evidence={"handle_id": self._handle_id},
        )

    def dispatch(self, _item: QueueItem) -> QueueDispatchResult:
        raise AssertionError("status test adapter must not dispatch")


def _service(tmp_path: Path) -> QueueService:
    service = QueueService.from_spec(
        normalize_queue_spec(
            {
                "db_path": str(tmp_path / "queue.sqlite"),
                "pools": [{"pool_name": "gpu-pool", "mode": "managed"}],
                "queues": [{"queue_name": "gpu", "pool_name": "gpu-pool"}],
            }
        ),
        clock=_clock("2020-01-01T00:00:00Z", "2020-01-01T00:00:01Z"),
    )
    service.start()
    return service


def _clock(*values: str):
    remaining = list(values)

    def next_value() -> str:
        if len(remaining) == 1:
            return remaining[0]
        return remaining.pop(0)

    return next_value
