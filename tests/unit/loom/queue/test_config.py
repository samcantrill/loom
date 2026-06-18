"""Unit coverage for queue service config normalization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from loom.queue import (
    QueueConfigError,
    QueuePoolMode,
    QueueServiceSpec,
    load_queue_spec,
    normalize_queue_spec,
    queue_spec_from_composed_config,
)


def test_normalize_queue_spec_accepts_queue_section_and_aliases(tmp_path: Path) -> None:
    spec = normalize_queue_spec(
        {
            "queue": {
                "service": {"db_path": str(tmp_path / "queue.sqlite")},
                "pools": [
                    {
                        "name": "gpu-pool",
                        "mode": "managed",
                        "resources": {"gpu": 1},
                    }
                ],
                "queues": [{"name": "gpu", "pool": "gpu-pool"}],
                "controller": {
                    "owner_id": "controller-1",
                    "default_pool_name": "gpu-pool",
                },
            }
        }
    )

    assert isinstance(spec, QueueServiceSpec)
    assert spec.db_path == str(tmp_path / "queue.sqlite")
    assert spec.pools[0].mode is QueuePoolMode.MANAGED
    assert spec.queue_for_name("gpu").pool_name == "gpu-pool"
    assert spec.controller.default_pool_name == "gpu-pool"


def test_normalize_queue_spec_rejects_invalid_topology() -> None:
    with pytest.raises(QueueConfigError, match="multiple queues"):
        normalize_queue_spec(
            {
                "pools": [{"pool_name": "pool-1", "mode": "managed"}],
                "queues": [
                    {"queue_name": "a", "pool_name": "pool-1"},
                    {"queue_name": "b", "pool_name": "pool-1"},
                ],
            }
        )


def test_queue_spec_from_composed_config_uses_resolved_queue_section() -> None:
    @dataclass(frozen=True)
    class Composed:
        resolved: dict[str, object]

    spec = queue_spec_from_composed_config(
        Composed(
            resolved={
                "queue": {
                    "pools": [{"pool_name": "cpu-pool", "mode": "delegated"}],
                    "queues": [{"queue_name": "cpu", "pool_name": "cpu-pool"}],
                }
            }
        )
    )

    assert spec.pool_names == ("cpu-pool",)
    assert spec.queue_names == ("cpu",)


@pytest.mark.optional_dependency
def test_load_queue_spec_uses_explicit_yaml_path(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    config_path = tmp_path / "queue.yaml"
    config_path.write_text(
        """
        queue:
          service:
            db_path: queue.sqlite
          pools:
            - pool_name: gpu-pool
              mode: managed
              resources:
                gpu: 1
          queues:
            - queue_name: gpu
              pool_name: gpu-pool
        """,
        encoding="utf-8",
    )

    spec = load_queue_spec(config_path)

    assert spec.db_path == "queue.sqlite"
    assert spec.queue_for_name("gpu").pool_name == "gpu-pool"
