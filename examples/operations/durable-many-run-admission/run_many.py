"""Submit a small deterministic project-owned parameter stream to Loom queue."""

from __future__ import annotations

import os
from pathlib import Path

from loom.fingerprints import hash_mapping
from loom.queue import (
    QueueClient,
    QueueEnqueueRequest,
    QueueService,
    normalize_queue_spec,
)


def main() -> None:
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", "./outputs"))
    client = QueueClient(
        QueueService.from_spec(
            normalize_queue_spec(
                {
                    "db_path": str(output_root / "queue.sqlite"),
                    "pools": [{"pool_name": "local-pool", "mode": "managed"}],
                    "queues": [{"queue_name": "local", "pool_name": "local-pool"}],
                }
            )
        )
    )
    client.start_service()
    for receipt in client.enqueue_many(_requests()):
        print(f"{receipt.disposition}: {receipt.canonical_queue_item_id}")


def _requests():
    for index, parameters in enumerate(({"width": 8}, {"width": 16})):
        normalized_science = {"project": "many-run-example", "parameters": parameters}
        yield QueueEnqueueRequest(
            queue_item_id=f"example-{index:04d}",
            queue_name="local",
            run_uri=f"file:///runs/example-{index:04d}",
            request={"parameters": parameters},
            scientific_fingerprint=hash_mapping(normalized_science),
        )


if __name__ == "__main__":
    main()
