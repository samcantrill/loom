"""Run three generic local queue commands over two static slots."""

from __future__ import annotations

# ruff: noqa: E402

import os
from pathlib import Path
import sys

REPO_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "pyproject.toml").is_file()
)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loom.pipeline.stores import WorkspaceIdentity
from loom.pipeline.stores.sqlite_coordination import SQLiteWorkspaceCoordinationStore
from loom.queue import (
    LaunchContract,
    QueueController,
    QueueEnqueueRequest,
    QueueService,
    normalize_queue_spec,
)
from loom.queue.assignments import (
    EnvironmentListBinding,
    StaticSlot,
    StaticSlotAssignmentProvider,
)
from loom.queue.local import LocalQueueDispatchAdapter
from loom.queue.status import build_queue_pool_status


HERE = Path(__file__).resolve().parent


def main() -> None:
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE / "output"))
    output_root.mkdir(parents=True, exist_ok=True)
    store = SQLiteWorkspaceCoordinationStore(output_root / "coordination.sqlite")
    store.create_workspace(WorkspaceIdentity("example-workspace"))
    for key in ("gpu", "slot-a-key", "slot-b-key"):
        store.set_resource_limit(
            "example-workspace", key, limit=2 if key == "gpu" else 1
        )
    service = QueueService.from_spec(
        normalize_queue_spec(
            {
                "schema_version": 2,
                "db_path": str(output_root / "queue.sqlite"),
                "controller": {"max_active_items": 2},
                "pools": [
                    {
                        "pool_name": "local-pool",
                        "mode": "managed",
                        "resources": {"gpu": 2},
                    }
                ],
                "queues": [{"queue_name": "local", "pool_name": "local-pool"}],
            }
        )
    )
    service.start()
    for index in range(1, 4):
        service.enqueue(
            QueueEnqueueRequest(
                queue_item_id=f"item-{index}",
                queue_name="local",
                run_uri=f"file:///example/item-{index}",
                launch_contract=LaunchContract(
                    adapter="local",
                    entrypoint="argv",
                    resources={"gpu": 1},
                    snapshot={"argv": [sys.executable, "-c", f"print('item-{index}')"]},
                ),
            )
        )
    provider = StaticSlotAssignmentProvider(
        store,
        workspace_id="example-workspace",
        slots=(
            StaticSlot("gpu", "slot-a", "slot-a-key", "a", "slot-a"),
            StaticSlot("gpu", "slot-b", "slot-b-key", "b", "slot-b"),
        ),
        bindings={"gpu": EnvironmentListBinding("gpu", "EXAMPLE_SLOTS", ",")},
    )
    adapter = LocalQueueDispatchAdapter(
        workspace_id="example-workspace",
        coordination_store=store,
        owner_id="example-controller",
        current_drift_inputs={},
        assignment_provider=provider,
        log_directory=output_root / "queue-state" / "logs",
    )
    controller = QueueController(service, adapters={"local": adapter})
    controller.run_cycle(pool_name="local-pool")
    active_status = build_queue_pool_status(
        service, pool_name="local-pool", adapters={"local": adapter}
    ).to_dict()
    if active_status["counts"]["active"] != 2 or active_status["counts"]["queued"] != 1:
        raise RuntimeError("example queue did not fill the two static slots")
    controller.drain_foreground(pool_name="local-pool", poll_interval_seconds=0.01)
    status = build_queue_pool_status(
        service, pool_name="local-pool", adapters={"local": adapter}
    ).to_dict()
    logs = sorted((output_root / "queue-state" / "logs").rglob("*.log"))
    stdout_logs = [path for path in logs if path.name.endswith(".stdout.log")]
    if len(logs) != 6 or {
        path.read_text(encoding="utf-8").strip() for path in stdout_logs
    } != {"item-1", "item-2", "item-3"}:
        raise RuntimeError("example queue did not produce distinct command logs")
    print("managed_local_queue:")
    print("  active_status:")
    for attempt in active_status["active_attempts"]:
        assignment = attempt["assignment"]
        attempt_logs = attempt["logs"]
        slots = [] if assignment is None else assignment["slots"]
        slot_ids = [slot["slot_id"] for slot in slots]
        stdout_path = None if attempt_logs is None else attempt_logs["stdout_path"]
        print(
            f"    {attempt['queue_item_id']}: slots={slot_ids} "
            f"stdout={stdout_path} source={attempt['evidence_source']}"
        )
    print(f"  succeeded: {status['counts']['succeeded']}")
    print(f"  active: {status['counts']['active']}")
    print(f"  queued: {status['counts']['queued']}")
    print(f"  logs_root: {output_root / 'queue-state' / 'logs'}")


if __name__ == "__main__":
    main()
