"""Unit coverage for queue record models."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from typing import cast

import pytest

from loom.queue import (
    CancellationRecord,
    DispatchHandle,
    LaunchContract,
    QueueClaim,
    QueueDefinition,
    QueueEnqueueDisposition,
    QueueEnqueueReceipt,
    QueueItem,
    QueueItemStatus,
    QueuePool,
    QueuePoolMode,
    QueueValidationError,
    RunIntent,
    validate_one_queue_per_pool,
)


def test_queue_item_serializes_versioned_plain_data() -> None:
    item = _queue_item()

    data = item.to_dict()

    assert data["schema_version"] == 2
    assert data["queue_item_id"] == "item-1"
    assert data["queue_name"] == "gpu"
    assert data["pool_name"] == "gpu-pool"
    assert data["run_uri"] == "file:///runs/queue/item-1"
    assert data["status"] == "QUEUED"
    assert data["dispatch_attempt"] == 1
    launch_contract = cast(dict[str, object], data["launch_contract"])
    assert launch_contract["drift_inputs"] == {"config_fingerprint": "sha256:abc"}
    assert launch_contract["delegated_verification"] == {"shared_workspace": False}
    assert QueueItem.from_dict(data) == item
    with pytest.raises(FrozenInstanceError):
        item.run_uri = "file:///runs/other"  # type: ignore[misc]


def test_queue_admission_identity_and_receipt_are_canonical() -> None:
    item = _queue_item()
    with_fingerprint = QueueItem(
        queue_item_id=item.queue_item_id,
        queue_name=item.queue_name,
        pool_name=item.pool_name,
        run_uri=item.run_uri,
        run_intent=item.run_intent,
        launch_contract=item.launch_contract,
        enqueued_at=item.enqueued_at,
        updated_at=item.updated_at,
        scientific_fingerprint="sha256:" + "A" * 64,
    )
    same_content = QueueItem(
        queue_item_id=item.queue_item_id,
        queue_name=item.queue_name,
        pool_name=item.pool_name,
        run_uri=item.run_uri,
        run_intent=item.run_intent,
        launch_contract=item.launch_contract,
        enqueued_at="2020-01-01T00:01:00Z",
        updated_at="2020-01-01T00:01:00Z",
        scientific_fingerprint="sha256:" + "a" * 64,
    )
    receipt = QueueEnqueueReceipt(
        disposition=QueueEnqueueDisposition.ENQUEUED,
        requested_queue_item_id=item.queue_item_id,
        canonical_queue_item_id=item.queue_item_id,
        queue_item=item,
        accepted_at=item.enqueued_at,
    )

    assert same_content.scientific_fingerprint == "sha256:" + "a" * 64
    assert with_fingerprint.admission_digest == same_content.admission_digest
    assert with_fingerprint.admission_digest != item.admission_digest
    assert QueueEnqueueReceipt.from_dict(receipt.to_dict()) == receipt


def test_queue_item_rejects_noncanonical_scientific_identity() -> None:
    with pytest.raises(QueueValidationError, match="scientific_fingerprint"):
        replace(_queue_item(), scientific_fingerprint="not-a-digest")


def test_queue_records_reject_unknown_fields_and_bad_versions() -> None:
    data = _queue_item().to_dict()
    data["extra"] = "nope"

    with pytest.raises(QueueValidationError, match="unknown field"):
        QueueItem.from_dict(data)

    data = _queue_item().to_dict()
    data["schema_version"] = 999
    with pytest.raises(QueueValidationError, match="unsupported schema version"):
        QueueItem.from_dict(data)

    with pytest.raises(QueueValidationError, match="schema_version"):
        QueuePool("gpu", QueuePoolMode.MANAGED, schema_version=True)
    pool_data = QueuePool("gpu", QueuePoolMode.MANAGED).to_dict()
    pool_data["schema_version"] = True
    with pytest.raises(QueueValidationError, match="schema_version"):
        QueuePool.from_dict(pool_data)


def test_queue_item_state_validation_requires_matching_records() -> None:
    item = _queue_item()
    claim = QueueClaim(
        claim_id="claim-1",
        owner_id="controller-1",
        claimed_at="2020-01-01T00:00:01Z",
        dispatch_attempt=1,
    )
    handle = DispatchHandle(
        adapter="local",
        handle_id="pid-1",
        dispatched_at="2020-01-01T00:00:02Z",
        dispatch_attempt=1,
    )

    with pytest.raises(QueueValidationError, match="CLAIMED"):
        QueueItem.from_dict(
            {
                **item.to_dict(),
                "status": QueueItemStatus.CLAIMED.value,
                "claim": None,
            }
        )
    assert (
        QueueItem.from_dict(
            {
                **item.to_dict(),
                "status": QueueItemStatus.CLAIMED.value,
                "updated_at": "2020-01-01T00:00:01Z",
                "claim": claim.to_dict(),
            }
        ).claim
        == claim
    )
    with pytest.raises(QueueValidationError, match="DISPATCHED"):
        QueueItem.from_dict(
            {
                **item.to_dict(),
                "status": QueueItemStatus.DISPATCHED.value,
                "updated_at": "2020-01-01T00:00:02Z",
                "claim": claim.to_dict(),
                "dispatch_handle": None,
            }
        )
    assert (
        QueueItem.from_dict(
            {
                **item.to_dict(),
                "status": QueueItemStatus.DISPATCHED.value,
                "updated_at": "2020-01-01T00:00:02Z",
                "claim": claim.to_dict(),
                "dispatch_handle": handle.to_dict(),
            }
        ).dispatch_handle
        == handle
    )


def test_queue_topology_enforces_one_queue_per_pool() -> None:
    pools = [
        QueuePool("gpu", QueuePoolMode.MANAGED, resources={"gpu": 1}),
        QueuePool("slurm", QueuePoolMode.DELEGATED),
    ]
    queues = [
        QueueDefinition("gpu-work", "gpu"),
        QueueDefinition("slurm-work", "slurm"),
    ]

    validate_one_queue_per_pool(pools, queues)

    with pytest.raises(QueueValidationError, match="multiple queues"):
        validate_one_queue_per_pool(
            [QueuePool("gpu", "managed")],
            [QueueDefinition("a", "gpu"), QueueDefinition("b", "gpu")],
        )
    with pytest.raises(QueueValidationError, match="missing queue"):
        validate_one_queue_per_pool([QueuePool("gpu", "managed")], [])


def test_queue_pool_resources_and_tags_are_frozen_at_construction() -> None:
    resources = {"gpu": 1}
    tags = {"project": "demo"}
    pool = QueuePool("gpu", QueuePoolMode.MANAGED, resources=resources)
    intent = RunIntent(run_uri="file:///runs/demo", tags=tags)

    resources["gpu"] = 2
    tags["project"] = "changed"
    assert pool.resources == {"gpu": 1}
    assert intent.tags == {"project": "demo"}
    with pytest.raises(TypeError):
        pool.resources["gpu"] = 3  # type: ignore[index]
    assert QueuePool.from_dict(pool.to_dict()) == pool
    assert RunIntent.from_dict(intent.to_dict()) == intent


def test_cancellation_record_preserves_evidence_slot() -> None:
    cancellation = CancellationRecord(
        requested_at="2020-01-01T00:00:03Z",
        requested_by="controller-1",
        reason="user-request",
        evidence={"adapter": "pending"},
    )

    assert CancellationRecord.from_dict(cancellation.to_dict()) == cancellation
    assert cancellation.to_dict()["evidence"] == {"adapter": "pending"}


def _queue_item() -> QueueItem:
    run_uri = "file:///runs/queue/item-1"
    return QueueItem(
        queue_item_id="item-1",
        queue_name="gpu",
        pool_name="gpu-pool",
        run_uri=run_uri,
        run_intent=RunIntent(
            run_uri=run_uri,
            request={"config": "config.yaml"},
            tags={"project": "demo"},
        ),
        launch_contract=LaunchContract(
            adapter="local",
            entrypoint="loom.pipeline:run",
            resources={"gpu": 1},
            snapshot={"config_uri": "file:///configs/config.yaml"},
            drift_inputs={"config_fingerprint": "sha256:abc"},
            delegated_verification={"shared_workspace": False},
        ),
        enqueued_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:00Z",
    )
