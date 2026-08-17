"""Contract coverage for queue config shapes."""

from __future__ import annotations

from loom.queue import normalize_queue_spec


def test_queue_service_spec_contract_shape() -> None:
    spec = normalize_queue_spec(
        {
            "schema_version": 1,
            "service": {"db_path": "queue.sqlite"},
            "pools": [
                {
                    "pool_name": "gpu-pool",
                    "mode": "managed",
                    "resources": {"gpu": 1},
                    "metadata": {"owner": "tests"},
                }
            ],
            "queues": [
                {
                    "queue_name": "gpu",
                    "pool_name": "gpu-pool",
                    "metadata": {"priority": "normal"},
                }
            ],
            "controller": {
                "owner_id": "controller-1",
                "default_pool_name": "gpu-pool",
                "metadata": {"mode": "fake"},
            },
            "metadata": {"workspace": "demo"},
        }
    )

    assert spec.to_dict() == {
        "schema_version": 1,
        "service": {"db_path": "queue.sqlite"},
        "pools": [
            {
                "schema_version": 1,
                "pool_name": "gpu-pool",
                "mode": "managed",
                "resources": {"gpu": 1},
                "metadata": {"owner": "tests"},
            }
        ],
        "queues": [
            {
                "schema_version": 1,
                "queue_name": "gpu",
                "pool_name": "gpu-pool",
                "metadata": {"priority": "normal"},
            }
        ],
        "controller": {
            "owner_id": "controller-1",
            "default_pool_name": "gpu-pool",
            "metadata": {"mode": "fake"},
        },
        "metadata": {"workspace": "demo"},
    }


def test_queue_config_schema_v2_normalizes_positive_cycle_limits() -> None:
    spec = normalize_queue_spec(
        {
            "schema_version": 2,
            "pools": [{"pool_name": "pool", "mode": "managed"}],
            "queues": [{"queue_name": "queue", "pool_name": "pool"}],
            "controller": {"max_active_items": 3},
        }
    )

    assert spec.controller.max_active_items == 3
    assert spec.controller.max_dispatches_per_cycle is None
    assert spec.to_dict()["controller"]["max_active_items"] == 3
