"""Integration coverage for the managed-local runtime facade."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import sys
from threading import Event
import time

import pytest

from loom.pipeline.stores import WorkspaceIdentity
from loom.pipeline.stores.sqlite_coordination import SQLiteWorkspaceCoordinationStore
from loom.queue import (
    QueueConflictError,
    QueueEnqueueRequest,
    QueueItemStatus,
    QueueServiceError,
    normalize_queue_spec,
)
from loom.queue.managed_local import (
    ManagedLocalQueueRuntime,
    ManagedLocalQueueRuntimeState,
    ManagedLocalShutdownTimeoutError,
)
from tests.support.processes import (
    capture_owned_process_identity,
    kill_owned_process,
    owned_process_is_live,
)


def test_runtime_gates_restart_recovery_and_drains_without_new_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = normalize_queue_spec(
        {
            "schema_version": 2,
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [
                {"pool_name": "local", "mode": "managed", "resources": {"gpu": 1}}
            ],
            "queues": [{"queue_name": "local", "pool_name": "local"}],
            "controller": {"owner_id": "runtime-owner", "max_active_items": 1},
        }
    )
    store = SQLiteWorkspaceCoordinationStore(tmp_path / "coordination.sqlite")
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    first_process = _Process(pid=101)
    runtime = ManagedLocalQueueRuntime.from_spec(
        spec,
        workspace_id="workspace-1",
        coordination_store=store,
        process_runner=_Runner([first_process]),
        clock=lambda: "2020-01-01T00:00:00Z",
    )
    runtime.start()
    runtime.service.enqueue(_request("active"))
    runtime.service.enqueue(_request("queued"))
    runtime.run_cycle()

    restarted = ManagedLocalQueueRuntime.from_spec(
        spec,
        workspace_id="workspace-1",
        coordination_store=store,
        process_runner=_Runner([_Process(pid=102)]),
        clock=lambda: "2020-01-01T00:00:00Z",
    )
    recovery = restarted.start()

    assert recovery.state is ManagedLocalQueueRuntimeState.RECOVERY_REQUIRED
    assert recovery.foreign_item_ids == ("active",)
    queued = restarted.service.read_item("queued")
    assert queued is not None and queued.status is QueueItemStatus.QUEUED

    first_process.returncode = 0
    monkeypatch.setattr(
        runtime.adapter,
        "cancel",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cancel")),
    )
    stop = Event()
    stop.set()
    stopped = runtime.serve(stop, poll_interval_seconds=0, wait=lambda _timeout: None)
    assert stopped.state is ManagedLocalQueueRuntimeState.STOPPED
    assert stopped.pool_status is not None
    assert stopped.pool_status.counts.queued == 1


def test_runtime_explicitly_resolves_one_contained_foreign_item_without_leases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = normalize_queue_spec(
        {
            "schema_version": 2,
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [
                {"pool_name": "local", "mode": "managed", "resources": {"gpu": 2}}
            ],
            "queues": [{"queue_name": "local", "pool_name": "local"}],
            "controller": {"owner_id": "runtime-owner", "max_active_items": 2},
        }
    )
    store = SQLiteWorkspaceCoordinationStore(tmp_path / "coordination.sqlite")
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=2)
    first_process = _Process(pid=110)
    first = ManagedLocalQueueRuntime.from_spec(
        spec,
        workspace_id="workspace-1",
        coordination_store=store,
        process_runner=_Runner([first_process, _Process(pid=111)]),
        clock=lambda: "2020-01-01T00:00:00Z",
    )
    first.start()
    first.service.enqueue(_request("active"))
    first.service.enqueue(_request("other"))
    first.run_cycle()

    restarted = ManagedLocalQueueRuntime.from_spec(
        spec,
        workspace_id="workspace-1",
        coordination_store=store,
        process_runner=_Runner([_Process(pid=112)]),
        clock=lambda: "2020-01-01T00:00:01Z",
    )
    assert restarted.start().state is ManagedLocalQueueRuntimeState.RECOVERY_REQUIRED
    before = store.read_resource_limit("workspace-1", "gpu")
    assert before is not None and before.value == 2
    monkeypatch.setattr(
        restarted.adapter,
        "inspect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("inspect")),
    )
    monkeypatch.setattr(
        restarted.adapter,
        "cancel",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cancel")),
    )

    with pytest.raises(QueueServiceError, match="confirmed_stopped=True"):
        restarted.resolve_recovery_unknown(
            "active",
            previous_processes_confirmed_stopped=False,
            requested_by="operator-1",
            reason="contained by supervisor",
        )
    still_active = restarted.service.read_item("active")
    assert (
        still_active is not None and still_active.status is QueueItemStatus.DISPATCHED
    )

    resolved = restarted.resolve_recovery_unknown(
        "active",
        previous_processes_confirmed_stopped=True,
        requested_by="operator-1",
        reason="contained by supervisor",
    )

    assert resolved.status is QueueItemStatus.UNKNOWN
    assert restarted.state is ManagedLocalQueueRuntimeState.RECOVERY_REQUIRED
    assert restarted.status().foreign_item_ids == ("other",)
    restarted.resolve_recovery_unknown(
        "other",
        previous_processes_confirmed_stopped=True,
        requested_by="operator-1",
        reason="contained by supervisor",
    )
    assert restarted.state is ManagedLocalQueueRuntimeState.READY
    after = store.read_resource_limit("workspace-1", "gpu")
    assert after is not None and after.value == 2
    event = restarted.service.inspect_item("active").audit_events[-1]
    assert event.detail == {
        "status": "UNKNOWN",
        "reason": "managed-local-explicit-recovery",
        "evidence": {
            "managed_local_recovery": {
                "action": "explicit_unknown_recovery",
                "requested_by": "operator-1",
                "reason": "contained by supervisor",
                "previous_status": "DISPATCHED",
                "previous_processes_confirmed_stopped": True,
                "previous_session_id": first.adapter.session_id,
            }
        },
    }


def test_runtime_resolves_a_claimed_foreign_item_to_unknown(tmp_path: Path) -> None:
    spec = normalize_queue_spec(
        {
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [
                {"pool_name": "local", "mode": "managed", "resources": {"gpu": 1}}
            ],
            "queues": [{"queue_name": "local", "pool_name": "local"}],
            "controller": {"owner_id": "runtime-owner"},
        }
    )
    store = SQLiteWorkspaceCoordinationStore(tmp_path / "coordination.sqlite")
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    runtime = ManagedLocalQueueRuntime.from_spec(
        spec,
        workspace_id="workspace-1",
        coordination_store=store,
        clock=lambda: "2020-01-01T00:00:00Z",
    )
    runtime.start()
    runtime.service.enqueue(_request("claimed"))
    _claim_fixture(runtime, "claimed", owner_id="runtime-owner", claim_id="previous-session-claim")
    assert runtime.start().state is ManagedLocalQueueRuntimeState.RECOVERY_REQUIRED

    resolved = runtime.resolve_recovery_unknown(
        "claimed",
        previous_processes_confirmed_stopped=True,
        requested_by="operator-1",
        reason="previous service group stopped",
    )

    assert resolved.status is QueueItemStatus.UNKNOWN
    assert resolved.dispatch_handle is not None
    assert resolved.dispatch_handle.handle_id.startswith("managed-local-recovery:")
    event = runtime.service.inspect_item("claimed").audit_events[-1]
    assert event.detail["evidence"] == {
        "managed_local_recovery": {
            "action": "explicit_unknown_recovery",
            "requested_by": "operator-1",
            "reason": "previous service group stopped",
            "previous_status": "CLAIMED",
            "previous_processes_confirmed_stopped": True,
        }
    }


def test_runtime_recovery_conflict_leaves_the_newer_item_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, restarted, _store, process = _foreign_runtime_pair(tmp_path)
    process.returncode = 0
    complete_item = restarted.service.complete_item

    def racing_complete_item(queue_item_id, *, status, reason, expected, evidence=None):  # noqa: ANN001, ANN202
        current = restarted.service.read_item(queue_item_id)
        assert current is not None
        restarted.service.cancel_item(
            queue_item_id,
            requested_by="concurrent-operator",
            reason="newer decision",
            expected=current,
        )
        return complete_item(
            queue_item_id,
            status=status,
            reason=reason,
            expected=expected,
            evidence=evidence,
        )

    monkeypatch.setattr(restarted.service, "complete_item", racing_complete_item)

    with pytest.raises(QueueConflictError):
        restarted.resolve_recovery_unknown(
            "active",
            previous_processes_confirmed_stopped=True,
            requested_by="operator-1",
            reason="previous service group stopped",
        )

    newer = restarted.service.read_item("active")
    assert newer is not None and newer.status is QueueItemStatus.CANCELLED
    assert runtime.service.read_item("active") == newer


def test_runtime_recovery_retains_two_slot_scalar_and_member_leases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _two_slot_spec(tmp_path)
    store = SQLiteWorkspaceCoordinationStore(tmp_path / "coordination.sqlite")
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=2)
    store.set_resource_limit("workspace-1", "gpu-0", limit=1)
    store.set_resource_limit("workspace-1", "gpu-1", limit=1)
    process = _Process(pid=120)
    first = ManagedLocalQueueRuntime.from_spec(
        spec,
        workspace_id="workspace-1",
        coordination_store=store,
        process_runner=_Runner([process]),
        clock=lambda: "2020-01-01T00:00:00Z",
    )
    first.start()
    first.service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="active",
            queue_name="local",
            run_uri="file:///runs/active",
            adapter="local",
            resources={"gpu": 2},
            snapshot={"argv": ["fake"]},
        )
    )
    first.run_cycle()
    process.returncode = 0
    restarted = ManagedLocalQueueRuntime.from_spec(
        spec,
        workspace_id="workspace-1",
        coordination_store=store,
        process_runner=_Runner([]),
        clock=lambda: "2020-01-01T00:00:01Z",
    )
    assert restarted.start().state is ManagedLocalQueueRuntimeState.RECOVERY_REQUIRED

    def forbidden_lease_mutation(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("foreign lease mutation")

    monkeypatch.setattr(store, "renew_lease", forbidden_lease_mutation)
    monkeypatch.setattr(store, "release_lease", forbidden_lease_mutation)

    resolved = restarted.resolve_recovery_unknown(
        "active",
        previous_processes_confirmed_stopped=True,
        requested_by="operator-1",
        reason="previous service group stopped",
    )

    assert resolved.status is QueueItemStatus.UNKNOWN
    for resource_key, expected_value in (("gpu", 2), ("gpu-0", 1), ("gpu-1", 1)):
        counter = store.read_resource_limit("workspace-1", resource_key)
        assert counter is not None and counter.value == expected_value


@pytest.mark.parametrize(
    ("shutdown_mode", "expected_state"),
    [
        ("drain", ManagedLocalQueueRuntimeState.DRAINING),
        ("cancel", ManagedLocalQueueRuntimeState.CANCELLING),
    ],
)
def test_runtime_shutdown_timeout_keeps_current_item_and_lease_active(
    tmp_path: Path,
    shutdown_mode: str,
    expected_state: ManagedLocalQueueRuntimeState,
) -> None:
    clock = _MutableClock("2020-01-01T00:00:00Z")
    spec = normalize_queue_spec(
        {
            "schema_version": 2,
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [
                {"pool_name": "local", "mode": "managed", "resources": {"gpu": 1}}
            ],
            "queues": [{"queue_name": "local", "pool_name": "local"}],
            "controller": {"owner_id": "runtime-owner", "max_active_items": 1},
        }
    )
    store = SQLiteWorkspaceCoordinationStore(tmp_path / "coordination.sqlite")
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    process = _Process(pid=112, exit_on_terminate=False, exit_on_kill=False)
    runtime = ManagedLocalQueueRuntime.from_spec(
        spec,
        workspace_id="workspace-1",
        coordination_store=store,
        process_runner=_Runner([process]),
        clock=clock,
    )
    runtime.start()
    runtime.service.enqueue(_request("active"))
    runtime.run_cycle()
    stop = Event()
    stop.set()

    with pytest.raises(ManagedLocalShutdownTimeoutError) as error:
        runtime.serve(
            stop,
            poll_interval_seconds=1,
            shutdown_mode=shutdown_mode,
            shutdown_timeout_seconds=0,
        )

    assert error.value.remaining_item_ids == ("active",)
    assert runtime.state is expected_state
    active = runtime.service.read_item("active")
    assert active is not None and active.status is QueueItemStatus.DISPATCHED
    counter = store.read_resource_limit("workspace-1", "gpu")
    assert counter is not None and counter.value == 1


def test_runtime_shutdown_deadline_precedes_post_wait_reconciliation(
    tmp_path: Path,
) -> None:
    clock = _MutableClock("2020-01-01T00:00:00Z")
    spec = normalize_queue_spec(
        {
            "schema_version": 2,
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [
                {"pool_name": "local", "mode": "managed", "resources": {"gpu": 1}}
            ],
            "queues": [{"queue_name": "local", "pool_name": "local"}],
            "controller": {"owner_id": "runtime-owner", "max_active_items": 1},
        }
    )
    store = SQLiteWorkspaceCoordinationStore(tmp_path / "coordination.sqlite")
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    process = _Process(pid=122)
    runtime = ManagedLocalQueueRuntime.from_spec(
        spec,
        workspace_id="workspace-1",
        coordination_store=store,
        process_runner=_Runner([process]),
        clock=clock,
    )
    runtime.start()
    runtime.service.enqueue(_request("active"))
    runtime.run_cycle()
    stop = Event()
    stop.set()
    waits: list[float] = []

    def cross_deadline(timeout: float) -> None:
        waits.append(timeout)
        clock.value = "2020-01-01T00:00:06Z"
        process.returncode = 0

    with pytest.raises(ManagedLocalShutdownTimeoutError) as error:
        runtime.serve(
            stop,
            poll_interval_seconds=10,
            shutdown_timeout_seconds=5,
            wait=cross_deadline,
        )

    assert waits == [5]
    assert error.value.remaining_item_ids == ("active",)
    assert runtime.state is ManagedLocalQueueRuntimeState.DRAINING
    active = runtime.service.read_item("active")
    assert active is not None and active.status is QueueItemStatus.DISPATCHED
    counter = store.read_resource_limit("workspace-1", "gpu")
    assert counter is not None and counter.value == 1


def test_runtime_explicit_cancel_only_finishes_current_work_after_cleanup(
    tmp_path: Path,
) -> None:
    spec = normalize_queue_spec(
        {
            "schema_version": 2,
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [
                {"pool_name": "local", "mode": "managed", "resources": {"gpu": 1}}
            ],
            "queues": [{"queue_name": "local", "pool_name": "local"}],
            "controller": {"owner_id": "runtime-owner", "max_active_items": 1},
        }
    )
    store = SQLiteWorkspaceCoordinationStore(tmp_path / "coordination.sqlite")
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    process = _Process(pid=113)
    runtime = ManagedLocalQueueRuntime.from_spec(
        spec,
        workspace_id="workspace-1",
        coordination_store=store,
        process_runner=_Runner([process]),
        clock=lambda: "2020-01-01T00:00:00Z",
    )
    runtime.start()
    runtime.service.enqueue(_request("active"))
    runtime.service.enqueue(_request("queued"))
    runtime.run_cycle()
    stop = Event()
    stop.set()

    stopped = runtime.serve(
        stop,
        poll_interval_seconds=0,
        shutdown_mode="cancel",
        wait=lambda _timeout: None,
    )

    assert process.returncode == -15
    assert stopped.state is ManagedLocalQueueRuntimeState.STOPPED
    assert stopped.pool_status is not None
    assert stopped.pool_status.counts.cancelled == 1
    assert stopped.pool_status.counts.queued == 1
    counter = store.read_resource_limit("workspace-1", "gpu")
    assert counter is not None and counter.value == 0


def test_runtime_cancel_does_not_touch_foreign_work(tmp_path: Path) -> None:
    runtime, _restarted, _store, process = _foreign_runtime_pair(tmp_path)
    runtime.service.enqueue(_request("foreign"))
    foreign = _claim_fixture(runtime, "foreign", owner_id="other-owner", claim_id="other-session-claim")
    stop = Event()
    stop.set()

    status = runtime.serve(
        stop,
        poll_interval_seconds=0,
        shutdown_mode="cancel",
        wait=lambda _timeout: None,
    )

    assert process.returncode == -15
    current = runtime.service.read_item("active")
    untouched = runtime.service.read_item("foreign")
    assert current is not None and current.status is QueueItemStatus.CANCELLED
    assert untouched == foreign
    assert status.state is ManagedLocalQueueRuntimeState.RECOVERY_REQUIRED


def test_runtime_cancel_observes_real_process_exit_before_item_and_lease_release(
    tmp_path: Path,
) -> None:
    spec = normalize_queue_spec(
        {
            "schema_version": 2,
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [
                {"pool_name": "local", "mode": "managed", "resources": {"gpu": 1}}
            ],
            "queues": [{"queue_name": "local", "pool_name": "local"}],
            "controller": {"owner_id": "runtime-owner", "max_active_items": 1},
            "adapters": {
                "local": {
                    "assignments": {
                        "local": {
                            "gpu": {
                                "provider": "static-slots",
                                "slots": [
                                    {
                                        "id": "gpu-0",
                                        "coordination_key": "gpu-0",
                                        "value": "0",
                                    }
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
    store = SQLiteWorkspaceCoordinationStore(tmp_path / "coordination.sqlite")
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    store.set_resource_limit("workspace-1", "gpu-0", limit=1)
    runtime = ManagedLocalQueueRuntime.from_spec(
        spec,
        workspace_id="workspace-1",
        coordination_store=store,
    )
    runtime.start()
    runtime.service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="active",
            queue_name="local",
            run_uri="file:///runs/active",
            adapter="local",
            resources={"gpu": 1},
            snapshot={"argv": [sys.executable, "-c", "import time; time.sleep(30)"]},
        )
    )
    runtime.service.enqueue(_request("queued"))
    runtime.service.enqueue(_request("foreign"))
    runtime.run_cycle()
    foreign = _claim_fixture(runtime, "foreign", owner_id="other-owner", claim_id="other-session-claim")
    active = runtime.service.read_item("active")
    assert active is not None and active.dispatch_handle is not None
    managed = active.dispatch_handle.evidence["managed_local"]
    assert isinstance(managed, Mapping)
    pid = managed["pid"]
    assert isinstance(pid, int) and not isinstance(pid, bool)
    identity = capture_owned_process_identity(pid)

    stop = Event()
    stop.set()
    try:
        status = runtime.serve(
            stop,
            poll_interval_seconds=0.01,
            shutdown_mode="cancel",
            wait=lambda _timeout: time.sleep(0.01),
        )
        assert not owned_process_is_live(identity)
    finally:
        kill_owned_process(identity, 9)

    assert not owned_process_is_live(identity)
    cancelled = runtime.service.read_item("active")
    queued = runtime.service.read_item("queued")
    assert cancelled is not None and cancelled.status is QueueItemStatus.CANCELLED
    assert queued is not None and queued.status is QueueItemStatus.QUEUED
    assert runtime.service.read_item("foreign") == foreign
    assert status.state is ManagedLocalQueueRuntimeState.RECOVERY_REQUIRED
    counter = store.read_resource_limit("workspace-1", "gpu")
    assert counter is not None and counter.value == 0
    member = store.read_resource_limit("workspace-1", "gpu-0")
    assert member is not None and member.value == 0


def test_runtime_recovery_rejects_a_current_session_item(tmp_path: Path) -> None:
    runtime, _restarted, _store, process = _foreign_runtime_pair(tmp_path)
    runtime.service.enqueue(_request("foreign"))
    foreign = _claim_fixture(runtime, "foreign", owner_id="other-owner", claim_id="other-session-claim")
    with pytest.raises(QueueServiceError, match="requires recovery"):
        runtime.run_cycle()
    current_before = runtime.service.read_item("active")

    with pytest.raises(QueueServiceError, match="foreign selected-pool item"):
        runtime.resolve_recovery_unknown(
            "active",
            previous_processes_confirmed_stopped=True,
            requested_by="operator-1",
            reason="previous service group stopped",
        )

    assert runtime.service.read_item("active") == current_before
    assert runtime.service.read_item("foreign") == foreign
    assert process.returncode is None


def test_runtime_degraded_work_blocks_refill_until_a_later_healthy_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = normalize_queue_spec(
        {
            "schema_version": 2,
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [
                {"pool_name": "local", "mode": "managed", "resources": {"gpu": 1}}
            ],
            "queues": [{"queue_name": "local", "pool_name": "local"}],
            "controller": {"owner_id": "runtime-owner", "max_active_items": 1},
        }
    )
    store = SQLiteWorkspaceCoordinationStore(tmp_path / "coordination.sqlite")
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    first_process = _Process(pid=101)
    runner = _Runner([first_process, _Process(pid=102)])
    runtime = ManagedLocalQueueRuntime.from_spec(
        spec,
        workspace_id="workspace-1",
        coordination_store=store,
        process_runner=runner,
        clock=lambda: "2020-01-01T00:00:00Z",
    )
    runtime.start()
    runtime.service.enqueue(_request("active"))
    runtime.service.enqueue(_request("queued"))
    runtime.run_cycle()

    inspect = runtime.adapter.inspect

    def unavailable_inspection(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
        raise RuntimeError("inspection unavailable")

    monkeypatch.setattr(runtime.adapter, "inspect", unavailable_inspection)
    degraded = runtime.run_cycle()

    assert runtime.state is ManagedLocalQueueRuntimeState.DEGRADED
    assert [step.outcome for step in degraded.reconciliation_steps] == ["degraded"]
    assert degraded.dispatch_steps == ()
    queued = runtime.service.read_item("queued")
    assert queued is not None and queued.status is QueueItemStatus.QUEUED

    monkeypatch.setattr(runtime.adapter, "inspect", inspect)
    first_process.returncode = 0
    recovered = runtime.run_cycle()

    assert runtime.state is ManagedLocalQueueRuntimeState.READY
    assert [step.outcome for step in recovered.reconciliation_steps] == ["completed"]
    assert [
        step.item.queue_item_id for step in recovered.dispatch_steps if step.item
    ] == ["queued"]


def test_runtime_uses_spec_owner_and_authored_static_assignment(tmp_path: Path) -> None:
    spec = normalize_queue_spec(
        {
            "schema_version": 2,
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [
                {"pool_name": "local", "mode": "managed", "resources": {"gpu": 1}}
            ],
            "queues": [{"queue_name": "local", "pool_name": "local"}],
            "controller": {"owner_id": "runtime-owner", "max_active_items": 1},
            "adapters": {
                "local": {
                    "assignments": {
                        "local": {
                            "gpu": {
                                "provider": "static-slots",
                                "slots": [
                                    {
                                        "id": "gpu-0",
                                        "coordination_key": "gpu-0",
                                        "value": "0",
                                    }
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
    store = SQLiteWorkspaceCoordinationStore(tmp_path / "coordination.sqlite")
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    store.set_resource_limit("workspace-1", "gpu-0", limit=1)
    runner = _Runner([_Process(pid=103)])
    runtime = ManagedLocalQueueRuntime.from_spec(
        spec,
        workspace_id="workspace-1",
        coordination_store=store,
        process_runner=runner,
        clock=lambda: "2020-01-01T00:00:00Z",
    )
    runtime.start()
    runtime.service.enqueue(_request("active"))

    runtime.run_cycle()
    status = runtime.status()

    assert runtime.owner_id == "runtime-owner"
    assert runtime.adapter.owner_id == "runtime-owner"
    item = runtime.service.read_item("active")
    assert item is not None and item.claim is not None
    assert item.claim.owner_id == "runtime-owner"
    assert runner.environments == [{"VISIBLE_GPUS": "0"}]
    assert status.pool_status is not None
    attempt = status.pool_status.active_attempts[0]
    assert attempt.owner_id == "runtime-owner"
    assert attempt.evidence_source == "same_session_live"
    assert attempt.assignment is not None
    assert attempt.assignment["provider_name"] == "static-slots"


def _request(queue_item_id: str) -> QueueEnqueueRequest:
    return QueueEnqueueRequest(
        queue_item_id=queue_item_id,
        queue_name="local",
        run_uri=f"file:///runs/{queue_item_id}",
        adapter="local",
        resources={"gpu": 1},
        snapshot={"argv": ["fake"]},
    )


class _Process:
    def __init__(
        self,
        *,
        pid: int,
        exit_on_terminate: bool = True,
        exit_on_kill: bool = True,
    ) -> None:
        self.pid = pid
        self.pgid = pid
        self.returncode: int | None = None
        self.exit_on_terminate = exit_on_terminate
        self.exit_on_kill = exit_on_kill

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        if self.exit_on_terminate:
            self.returncode = -15

    def kill(self) -> None:
        if self.exit_on_kill:
            self.returncode = -9


class _MutableClock:
    def __init__(self, value: str) -> None:
        self.value = value

    def __call__(self) -> str:
        return self.value


class _Runner:
    def __init__(self, processes: list[_Process]) -> None:
        self._processes = processes
        self.environments: list[dict[str, str]] = []

    def start(self, argv, *, cwd=None, env=None, stdout_path=None, stderr_path=None):  # noqa: ANN001, ANN201
        self.environments.append(dict(env or {}))
        return self._processes.pop(0)


def _foreign_runtime_pair(tmp_path):  # noqa: ANN001, ANN202
    spec = normalize_queue_spec(
        {
            "schema_version": 2,
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [
                {"pool_name": "local", "mode": "managed", "resources": {"gpu": 1}}
            ],
            "queues": [{"queue_name": "local", "pool_name": "local"}],
            "controller": {"owner_id": "runtime-owner", "max_active_items": 1},
        }
    )
    store = SQLiteWorkspaceCoordinationStore(tmp_path / "coordination.sqlite")
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    process = _Process(pid=121)
    first = ManagedLocalQueueRuntime.from_spec(
        spec,
        workspace_id="workspace-1",
        coordination_store=store,
        process_runner=_Runner([process]),
        clock=lambda: "2020-01-01T00:00:00Z",
    )
    first.start()
    first.service.enqueue(_request("active"))
    first.run_cycle()
    restarted = ManagedLocalQueueRuntime.from_spec(
        spec,
        workspace_id="workspace-1",
        coordination_store=store,
        process_runner=_Runner([]),
        clock=lambda: "2020-01-01T00:00:01Z",
    )
    assert restarted.start().state is ManagedLocalQueueRuntimeState.RECOVERY_REQUIRED
    return first, restarted, store, process


def _claim_fixture(runtime, item_id, *, owner_id, claim_id):  # noqa: ANN001, ANN202
    item = runtime.service.read_item(item_id)
    assert item is not None
    claimed = runtime.service.repository._claim_selection_candidate(
        item_id,
        pool_name=item.pool_name,
        expected_dispatch_attempt=item.dispatch_attempt,
        owner_id=owner_id,
        claim_id=claim_id,
        preference_id="test.fixture",
        reason_code="test.fixture",
    )
    assert claimed is not None
    return claimed


def _two_slot_spec(tmp_path):  # noqa: ANN001, ANN202
    return normalize_queue_spec(
        {
            "schema_version": 2,
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [
                {"pool_name": "local", "mode": "managed", "resources": {"gpu": 2}}
            ],
            "queues": [{"queue_name": "local", "pool_name": "local"}],
            "controller": {"owner_id": "runtime-owner"},
            "adapters": {
                "local": {
                    "assignments": {
                        "local": {
                            "gpu": {
                                "provider": "static-slots",
                                "slots": [
                                    {"id": "gpu-0", "coordination_key": "gpu-0", "value": "0"},
                                    {"id": "gpu-1", "coordination_key": "gpu-1", "value": "1"},
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
