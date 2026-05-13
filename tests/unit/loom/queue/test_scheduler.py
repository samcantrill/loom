"""Unit coverage for private queue selection helpers."""

from __future__ import annotations

from dataclasses import replace

from loom.queue import LaunchContract, QueueClaim, QueueItem, QueueItemStatus, RunIntent
from loom.queue._scheduler import select_fifo_item


def test_select_fifo_item_returns_oldest_queued_item_for_pool() -> None:
    later = _item("later", "gpu", "2020-01-01T00:00:02Z")
    other_pool = _item("other", "cpu", "2020-01-01T00:00:00Z")
    older = _item("older", "gpu", "2020-01-01T00:00:01Z")
    claimed = replace(
        _item("claimed", "gpu", "2020-01-01T00:00:00Z"),
        status=QueueItemStatus.CLAIMED,
        claim=QueueClaim(
            claim_id="claim-1",
            owner_id="controller-1",
            claimed_at="2020-01-01T00:00:00Z",
            dispatch_attempt=1,
        ),
    )

    assert select_fifo_item([later, other_pool, older, claimed], pool_name="gpu") == older
    assert select_fifo_item([later, other_pool, older], pool_name="cpu") == other_pool
    assert select_fifo_item([claimed], pool_name="gpu") is None


def _item(item_id: str, pool_name: str, enqueued_at: str) -> QueueItem:
    run_uri = f"file:///runs/{item_id}"
    return QueueItem(
        queue_item_id=item_id,
        queue_name=f"{pool_name}-queue",
        pool_name=pool_name,
        run_uri=run_uri,
        run_intent=RunIntent(run_uri=run_uri),
        launch_contract=LaunchContract(adapter="local", entrypoint="entry"),
        enqueued_at=enqueued_at,
        updated_at=enqueued_at,
    )
