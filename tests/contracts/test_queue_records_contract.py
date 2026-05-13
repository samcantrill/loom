"""Contract coverage for public queue record shapes."""

from __future__ import annotations

from loom.queue import (
    DispatchHandle,
    LaunchContract,
    QueueDefinition,
    QueueItem,
    QueueItemStatus,
    QueuePool,
    RunIntent,
)


def test_queue_item_contract_shape() -> None:
    run_uri = "file:///runs/queue/item-1"
    item = QueueItem(
        queue_item_id="item-1",
        queue_name="gpu",
        pool_name="gpu-pool",
        run_uri=run_uri,
        run_intent=RunIntent(
            run_uri=run_uri,
            request={"config": "config.yaml"},
            tags={"project": "demo"},
            metadata={"owner": "contract"},
        ),
        launch_contract=LaunchContract(
            adapter="local",
            entrypoint="loom.pipeline:run",
            resources={"gpu": 1},
            snapshot={"config_fingerprint": "sha256:abc"},
            drift_inputs={"config_fingerprint": "sha256:abc"},
            delegated_verification={"shared_workspace": False},
        ),
        enqueued_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:00Z",
    )

    assert item.to_dict() == {
        "schema_version": 1,
        "queue_item_id": "item-1",
        "queue_name": "gpu",
        "pool_name": "gpu-pool",
        "run_uri": run_uri,
        "status": "QUEUED",
        "dispatch_attempt": 1,
        "enqueued_at": "2020-01-01T00:00:00Z",
        "updated_at": "2020-01-01T00:00:00Z",
        "run_intent": {
            "schema_version": 1,
            "run_uri": run_uri,
            "request": {"config": "config.yaml"},
            "tags": {"project": "demo"},
            "metadata": {"owner": "contract"},
        },
        "launch_contract": {
            "schema_version": 1,
            "adapter": "local",
            "entrypoint": "loom.pipeline:run",
            "resources": {"gpu": 1},
            "snapshot": {"config_fingerprint": "sha256:abc"},
            "drift_inputs": {"config_fingerprint": "sha256:abc"},
            "delegated_verification": {"shared_workspace": False},
            "metadata": {},
        },
        "claim": None,
        "dispatch_handle": None,
        "cancellation": None,
        "metadata": {},
    }


def test_queue_definition_and_pool_contract_shape() -> None:
    assert QueuePool("gpu-pool", "managed", resources={"gpu": 1}).to_dict() == {
        "schema_version": 1,
        "pool_name": "gpu-pool",
        "mode": "managed",
        "resources": {"gpu": 1},
        "metadata": {},
    }
    assert QueueDefinition("gpu", "gpu-pool").to_dict() == {
        "schema_version": 1,
        "queue_name": "gpu",
        "pool_name": "gpu-pool",
        "metadata": {},
    }


def test_dispatch_handle_contract_shape() -> None:
    handle = DispatchHandle(
        adapter="slurm",
        handle_id="12345",
        dispatched_at="2020-01-01T00:00:01Z",
        dispatch_attempt=1,
        evidence={"sbatch": "ok"},
    )

    assert handle.to_dict() == {
        "schema_version": 1,
        "adapter": "slurm",
        "handle_id": "12345",
        "dispatched_at": "2020-01-01T00:00:01Z",
        "dispatch_attempt": 1,
        "evidence": {"sbatch": "ok"},
    }
    assert QueueItemStatus.QUEUED.value == "QUEUED"
