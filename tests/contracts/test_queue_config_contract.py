"""Contract coverage for queue config shapes."""

from __future__ import annotations

from dataclasses import replace

import pytest

from loom.queue import (
    QueueConfigError,
    QueueControllerSpec,
    QUEUE_RECORD_SCHEMA_VERSION,
    normalize_queue_spec,
)


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
                "schema_version": QUEUE_RECORD_SCHEMA_VERSION,
                "pool_name": "gpu-pool",
                "mode": "managed",
                "resources": {"gpu": 1},
                "metadata": {"owner": "tests"},
            }
        ],
        "queues": [
            {
                "schema_version": QUEUE_RECORD_SCHEMA_VERSION,
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
    serialized = spec.to_dict()
    controller = serialized["controller"]
    assert isinstance(controller, dict)
    assert controller["max_active_items"] == 3


def test_queue_config_schema_v2_accepts_only_static_assignment_records() -> None:
    spec = normalize_queue_spec(
        {
            "schema_version": 2,
            "pools": [
                {"pool_name": "pool", "mode": "managed", "resources": {"gpu": 2}}
            ],
            "queues": [{"queue_name": "queue", "pool_name": "pool"}],
            "adapters": {
                "local": {
                    "assignments": {
                        "pool": {
                            "gpu": {
                                "provider": "static-slots",
                                "slots": [
                                    {
                                        "id": "zero",
                                        "coordination_key": "gpu-0",
                                        "value": "0",
                                    },
                                    {
                                        "id": "one",
                                        "coordination_key": "gpu-1",
                                        "value": "1",
                                        "label": "second",
                                    },
                                ],
                                "binding": {
                                    "type": "environment-list",
                                    "name": "VISIBLE_GPUS",
                                    "separator": ",",
                                },
                            }
                        }
                    }
                }
            },
        }
    )

    assignment = spec.local_assignments["pool"]["gpu"]
    assert [slot.slot_id for slot in assignment.slots] == ["zero", "one"]
    assert assignment.to_dict()["provider"] == "static-slots"


def test_queue_config_rejects_static_slot_key_colliding_with_any_logical_resource() -> (
    None
):
    config = _static_assignment_config()
    assignments = config["adapters"]["local"]["assignments"]  # type: ignore[index]
    assignments["pool"]["gpu"]["slots"][0]["coordination_key"] = "cpu"  # type: ignore[index]

    with pytest.raises(QueueConfigError, match="must not collide"):
        normalize_queue_spec(config)


def test_queue_config_rejects_static_inventory_mismatching_pool_capacity() -> None:
    config = _static_assignment_config()
    assignments = config["adapters"]["local"]["assignments"]  # type: ignore[index]
    assignments["pool"]["gpu"]["slots"].pop()  # type: ignore[index]

    with pytest.raises(QueueConfigError, match="inventory must equal"):
        normalize_queue_spec(config)


def test_queue_config_schema_v1_rejects_assignment_records() -> None:
    config = _static_assignment_config()
    config["schema_version"] = 1

    with pytest.raises(QueueConfigError, match="require queue config schema_version 2"):
        normalize_queue_spec(config)


def test_unversioned_queue_config_keeps_legacy_schema_v1_defaults() -> None:
    spec = normalize_queue_spec(
        {
            "pools": [{"pool_name": "pool", "mode": "managed"}],
            "queues": [{"queue_name": "queue", "pool_name": "pool"}],
        }
    )

    assert spec.schema_version == 1
    assert spec.controller.max_active_items == 1
    assert spec.controller.max_dispatches_per_cycle is None
    controller = spec.to_dict()["controller"]
    assert isinstance(controller, dict)
    assert "max_active_items" not in controller
    assert "max_dispatches_per_cycle" not in controller


def test_unversioned_queue_config_rejects_schema_v2_cycle_limits() -> None:
    with pytest.raises(QueueConfigError, match="require queue config schema_version 2"):
        normalize_queue_spec(
            {
                "pools": [{"pool_name": "pool", "mode": "managed"}],
                "queues": [{"queue_name": "queue", "pool_name": "pool"}],
                "controller": {"max_active_items": 2},
            }
        )


@pytest.mark.parametrize(
    "controller",
    [
        QueueControllerSpec(max_active_items=2),
        QueueControllerSpec(max_dispatches_per_cycle=2),
    ],
)
def test_queue_config_schema_v1_constructor_rejects_cycle_limits(
    controller: QueueControllerSpec,
) -> None:
    legacy = normalize_queue_spec(
        {
            "schema_version": 1,
            "pools": [{"pool_name": "pool", "mode": "managed"}],
            "queues": [{"queue_name": "queue", "pool_name": "pool"}],
        }
    )

    with pytest.raises(QueueConfigError, match="require queue config schema_version 2"):
        replace(legacy, controller=controller)


def _static_assignment_config() -> dict[str, object]:
    return {
        "schema_version": 2,
        "pools": [
            {
                "pool_name": "pool",
                "mode": "managed",
                "resources": {"gpu": 2, "cpu": 1},
            }
        ],
        "queues": [{"queue_name": "queue", "pool_name": "pool"}],
        "adapters": {
            "local": {
                "assignments": {
                    "pool": {
                        "gpu": {
                            "provider": "static-slots",
                            "slots": [
                                {
                                    "id": "zero",
                                    "coordination_key": "gpu-0",
                                    "value": "0",
                                },
                                {
                                    "id": "one",
                                    "coordination_key": "gpu-1",
                                    "value": "1",
                                },
                            ],
                            "binding": {
                                "type": "environment-list",
                                "name": "VISIBLE_GPUS",
                                "separator": ",",
                            },
                        }
                    }
                }
            }
        },
    }
