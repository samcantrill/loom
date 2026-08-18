"""Run generic managed-local work through the supported runtime facade."""

from __future__ import annotations

# ruff: noqa: E402

import os
from pathlib import Path
import sys
import tempfile
from threading import Event

REPO_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "pyproject.toml").is_file()
)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loom.pipeline.stores import WorkspaceIdentity
from loom.pipeline.stores.sqlite_coordination import SQLiteWorkspaceCoordinationStore
from loom.queue import LaunchContract, QueueEnqueueRequest, normalize_queue_spec
from loom.queue.managed_local import ManagedLocalQueueRuntime


HERE = Path(__file__).resolve().parent
WORKSPACE_ID = "example-workspace"
OWNER_ID = "example-runtime"


def main() -> None:
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE / "output"))
    output_root.mkdir(parents=True, exist_ok=True)
    run_root = Path(tempfile.mkdtemp(prefix="run-", dir=output_root))
    store = SQLiteWorkspaceCoordinationStore(run_root / "coordination.sqlite")
    store.create_workspace(WorkspaceIdentity(WORKSPACE_ID))
    for key in ("accelerator", "accelerator-slot-a", "accelerator-slot-b"):
        store.set_resource_limit(
            WORKSPACE_ID, key, limit=2 if key == "accelerator" else 1
        )

    runtime = ManagedLocalQueueRuntime.from_spec(
        _spec(run_root),
        workspace_id=WORKSPACE_ID,
        coordination_store=store,
        log_directory=run_root / "queue-state" / "logs",
    )
    runtime.start()
    release_first_item = run_root / "release-item-1"
    for item_id, amount in (("item-1", 2), ("item-2", 1), ("item-3", 1)):
        runtime.service.enqueue(
            _request(
                item_id,
                amount,
                release_path=release_first_item if item_id == "item-1" else None,
            )
        )

    # The first cycle starts the two-slot request.  The runtime's serve loop
    # owns all later reconciliation, refill, renewal, and graceful shutdown.
    runtime.run_cycle()
    active_status = runtime.status().to_dict()
    try:
        _assert_active_two_slot_item(active_status)
    finally:
        # The first child waits on this bounded, filesystem-visible signal so
        # live-status observation does not depend on scheduler timing.
        release_first_item.touch()
    _serve_until_example_completes(runtime)
    status = runtime.status().to_dict()
    _assert_completed_example(status, run_root)

    print("managed_local_queue:")
    print(f"  owner: {runtime.owner_id}")
    print("  active_status:")
    pool_status = active_status["pool_status"]
    assert isinstance(pool_status, dict)
    attempts = pool_status["active_attempts"]
    assert isinstance(attempts, list)
    for attempt in attempts:
        assert isinstance(attempt, dict)
        assignment = attempt["assignment"]
        logs = attempt["logs"]
        assert isinstance(assignment, dict) and isinstance(logs, dict)
        slots = assignment["slots"]
        assert isinstance(slots, list)
        slot_ids = [slot["slot_id"] for slot in slots if isinstance(slot, dict)]
        print(
            f"    {attempt['queue_item_id']}: slots={slot_ids} "
            f"stdout={logs['stdout_path']} source={attempt['evidence_source']}"
        )
    final_pool = status["pool_status"]
    assert isinstance(final_pool, dict)
    counts = final_pool["counts"]
    assert isinstance(counts, dict)
    print(f"  succeeded: {counts['succeeded']}")
    print(f"  active: {counts['active']}")
    print(f"  queued: {counts['queued']}")
    print(f"  logs_root: {run_root / 'queue-state' / 'logs'}")


def _spec(run_root: Path):  # noqa: ANN201
    return normalize_queue_spec(
        {
            "schema_version": 2,
            "db_path": str(run_root / "queue.sqlite"),
            "controller": {"owner_id": OWNER_ID, "max_active_items": 2},
            "pools": [
                {
                    "pool_name": "local-pool",
                    "mode": "managed",
                    "resources": {"accelerator": 2},
                }
            ],
            "queues": [{"queue_name": "local", "pool_name": "local-pool"}],
            "adapters": {
                "local": {
                    "assignments": {
                        "local-pool": {
                            "accelerator": {
                                "provider": "static-slots",
                                "slots": [
                                    {
                                        "id": "slot-a",
                                        "coordination_key": "accelerator-slot-a",
                                        "value": "a",
                                        "label": "slot-a",
                                    },
                                    {
                                        "id": "slot-b",
                                        "coordination_key": "accelerator-slot-b",
                                        "value": "b",
                                        "label": "slot-b",
                                    },
                                ],
                                "binding": {
                                    "type": "environment-list",
                                    "name": "LOOM_ASSIGNED_ACCELERATORS",
                                    "separator": ",",
                                },
                            }
                        }
                    }
                }
            },
        }
    )


def _request(
    item_id: str, amount: int, *, release_path: Path | None = None
) -> QueueEnqueueRequest:
    command = "\n".join(
        (
            "import os",
            "from pathlib import Path",
            "import time",
            f"print('{item_id}:' + os.environ['LOOM_ASSIGNED_ACCELERATORS'], flush=True)",
            *(
                (
                    f"release_path = Path({str(release_path)!r})",
                    "deadline = time.monotonic() + 5",
                    "while not release_path.exists():",
                    "    if time.monotonic() >= deadline:",
                    "        raise RuntimeError('example release signal timed out')",
                    "    time.sleep(0.01)",
                )
                if release_path is not None
                else ("time.sleep(0.02)",)
            ),
        )
    )
    return QueueEnqueueRequest(
        queue_item_id=item_id,
        queue_name="local",
        run_uri=f"file:///example/{item_id}",
        launch_contract=LaunchContract(
            adapter="local",
            entrypoint="argv",
            resources={"accelerator": amount},
            snapshot={"argv": [sys.executable, "-c", command]},
        ),
    )


def _serve_until_example_completes(runtime: ManagedLocalQueueRuntime) -> None:
    """Use an Event as a finite example harness without duplicating the loop."""

    stop_event = Event()

    def wait(timeout: float) -> bool:
        snapshot = runtime.service.read_pool_snapshot(runtime.pool_name)
        if snapshot.items and all(
            item.status.value == "SUCCEEDED" for item in snapshot.items
        ):
            stop_event.set()
        return stop_event.wait(min(timeout, 0.01))

    runtime.serve(stop_event, poll_interval_seconds=0.01, wait=wait)


def _assert_active_two_slot_item(status: dict[str, object]) -> None:
    pool_status = status["pool_status"]
    assert isinstance(pool_status, dict)
    attempts = pool_status["active_attempts"]
    assert isinstance(attempts, list) and len(attempts) == 1
    attempt = attempts[0]
    assert isinstance(attempt, dict)
    assignment = attempt["assignment"]
    assert isinstance(assignment, dict)
    slots = assignment["slots"]
    assert isinstance(slots, list)
    slot_ids = [slot["slot_id"] for slot in slots if isinstance(slot, dict)]
    if (
        attempt["queue_item_id"] != "item-1"
        or attempt["owner_id"] != OWNER_ID
        or attempt["evidence_source"] != "same_session_live"
        or len(slot_ids) != 2
        or len(set(slot_ids)) != 2
    ):
        raise RuntimeError("example runtime did not expose one live two-slot item")


def _assert_completed_example(status: dict[str, object], run_root: Path) -> None:
    pool_status = status["pool_status"]
    assert isinstance(pool_status, dict)
    counts = pool_status["counts"]
    if (
        not isinstance(counts, dict)
        or counts["succeeded"] != 3
        or counts["active"]
        or counts["queued"]
    ):
        raise RuntimeError("example queue did not finish and refill all work")
    logs = sorted((run_root / "queue-state" / "logs").rglob("*.log"))
    stdout_logs = [path for path in logs if path.name.endswith(".stdout.log")]
    if len(logs) != 6 or {
        path.read_text(encoding="utf-8").strip() for path in stdout_logs
    } != {"item-1:a,b", "item-2:a", "item-3:b"}:
        raise RuntimeError("example queue did not produce distinct command logs")


if __name__ == "__main__":
    main()
