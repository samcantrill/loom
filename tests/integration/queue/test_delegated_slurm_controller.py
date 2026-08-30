"""Integration coverage for delegated SLURM queue controller handoff."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import json
from pathlib import Path
from typing import cast

import pytest

from loom.pipeline.executors.slurm import SlurmManifestError
from loom.pipeline.executors.slurm.commands import (
    FakeSlurmCommandRunner,
    SlurmCommandResult,
)
from loom.pipeline.executors.slurm.live import (
    SlurmSchedulerOperation,
    SlurmSchedulerOperationState,
    SlurmSchedulerStatusSnapshot,
    SlurmSubmittedJob,
    read_slurm_live_manifest,
    write_slurm_live_manifest,
)
from loom.pipeline.executors.slurm.paths import resolve_slurm_generated_artifact_path
from loom.pipeline.executors.slurm.planning import (
    plan_afterok_slurm_dry_run,
    plan_single_job_slurm_dry_run,
)
from loom.pipeline.status import RunStatus, RunStatusRecord
from loom.queue import (
    LaunchContract,
    QueueController,
    QueueDispatchDisposition,
    QueueEnqueueRequest,
    QueueItem,
    QueueItemStatus,
    QueueService,
    RunIntent,
    SQLiteQueueRepository,
    normalize_queue_spec,
)
from loom.queue.slurm import (
    SlurmQueueDispatchAdapter,
    SlurmPreparedRunLaunch,
    prepared_slurm_launch,
)
from loom.queue.status import inspect_managed_queue_status
from loom.serialization import PlainData
from tests.integration.pipeline.test_slurm_dry_run_planning import _prepared_store


def test_delegated_slurm_foreground_handoff_and_recovery_reuses_handle(
    tmp_path: Path,
) -> None:
    clock = _clock(
        "2020-01-01T00:00:00Z",
        "2020-01-01T00:00:01Z",
        "2020-01-01T00:00:02Z",
        "2020-01-01T00:00:03Z",
        "2020-01-01T00:00:04Z",
        "2020-01-01T00:00:05Z",
    )
    service = _started_service(tmp_path, clock=clock)
    service.enqueue(_request("item-1"))
    runner = FakeSlurmCommandRunner(
        starting_job_id=700,
        scripted_results={
            "squeue": [
                SlurmCommandResult(
                    command="squeue",
                    argv=("squeue",),
                    returncode=0,
                    stdout="700|PENDING|Resources\n",
                ),
                SlurmCommandResult(
                    command="squeue",
                    argv=("squeue",),
                    returncode=0,
                    stdout="700|RUNNING|None\n",
                ),
            ],
            "sacct": [
                SlurmCommandResult(command="sacct", argv=("sacct",), returncode=0)
            ],
        },
    )
    adapter = SlurmQueueDispatchAdapter(
        command_runner=runner,
        authority_run_exists=lambda run_uri: False,
        clock=clock,
    )
    controller = QueueController(service, adapters={"slurm": adapter}, clock=clock)

    result = controller.drain_foreground(
        pool_name="slurm-pool",
        poll_interval_seconds=0,
    )
    dispatched = service.read_item("item-1")
    statuses = inspect_managed_queue_status(service, adapters={"slurm": adapter})

    assert [step.outcome for step in result.steps] == ["dispatched", "handoff"]
    assert len(result.recovery_records) == 1
    assert dispatched is not None
    assert dispatched.status is QueueItemStatus.DISPATCHED
    assert dispatched.run_uri == "file:///runs/item-1"
    assert dispatched.dispatch_handle is not None
    assert dispatched.dispatch_handle.evidence["scheduler_job_id"] == "700"
    assert dispatched.dispatch_handle.evidence["loom_resource_leases_held"] is False
    assert statuses[0].adapter_inspection is not None
    assert statuses[0].adapter_inspection.handoff_complete is True
    status_evidence = _mapping(statuses[0].adapter_inspection.evidence)
    authority_run = _mapping(status_evidence["authority_run"])
    assert authority_run["missing_authority_run"] is True
    assert [call[0] for call in runner.calls].count("sbatch") == 1

    recovery_runner = FakeSlurmCommandRunner(
        scripted_results={
            "sacct": [
                SlurmCommandResult(
                    command="sacct",
                    argv=("sacct",),
                    returncode=0,
                    stdout="700|COMPLETED|0:0\n",
                )
            ],
            "squeue": [
                SlurmCommandResult(command="squeue", argv=("squeue",), returncode=0)
            ],
        }
    )
    recovered = QueueController(
        service,
        adapters={"slurm": SlurmQueueDispatchAdapter(command_runner=recovery_runner)},
        clock=clock,
    ).run_once(pool_name="slurm-pool")

    assert recovered.outcome == "completed"
    assert recovered.item is not None
    assert recovered.item.status is QueueItemStatus.SUCCEEDED
    assert recovered.item.run_uri == "file:///runs/item-1"
    assert [call[0] for call in recovery_runner.calls] == ["sacct", "squeue"]


def test_prepared_slurm_driver_reuses_run_manifest_without_second_job_inventory(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_store(
        tmp_path,
        {"extract": (), "report": ("extract",)},
        authority_backed=True,
    )
    planning = plan_afterok_slurm_dry_run(
        run_store=store,
        run_uri=run_uri,
        planning_id="queued-afterok",
        created_at="2026-08-30T00:00:00Z",
    )
    service = _started_service(tmp_path, clock=_clock("2026-08-30T00:00:00Z"))
    launch = prepared_slurm_launch(planning)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="prepared-item",
            queue_name="slurm",
            run_uri=run_uri,
            launch_contract=LaunchContract(
                adapter="slurm",
                entrypoint="prepared-run",
                snapshot=launch.to_snapshot(),
                delegated_verification={"shared_workspace": True},
            ),
        )
    )
    runner = _PersistCheckingRunner(
        planning.manifest_artifact.local_path, starting_job_id=900
    )
    controller = QueueController(
        service,
        adapters={
            "slurm": SlurmQueueDispatchAdapter(command_runner=runner, run_store=store)
        },
    )

    result = controller.drive_foreground(pool_name="slurm-pool", until_quiescent=True)
    item = service.read_item("prepared-item")
    operation = store.latest_submitted_operation(run_uri)

    assert result.quiescent is True
    assert result.cycles[0].dispatch_steps[0].outcome == "dispatched"
    assert item is not None and item.dispatch_handle is not None
    evidence = _mapping(item.dispatch_handle.evidence)
    assert evidence["prepared_run"] == {
        "run_uri": run_uri,
        "mode": "slurm-afterok",
        "planning_id": "queued-afterok",
        "manifest_relative_path": "slurm/submissions/queued-afterok/manifest.json",
        "submission_digest": launch.submission_digest,
    }
    assert "result" not in evidence
    assert "scheduler_job_ids" not in evidence
    assert operation is not None
    assert operation.backend_metadata["queue"] == {"queue_item_id": "prepared-item"}
    assert [call[0] for call in runner.calls].count("sbatch") == 2
    assert runner.persisted_before_call_count == 2
    manifest = _live_manifest(store, run_uri)
    scheduler_operations = cast(
        tuple[SlurmSchedulerOperation, ...], manifest.scheduler_operations
    )
    assert [operation.state for operation in scheduler_operations] == [
        SlurmSchedulerOperationState.ACCEPTED,
        SlurmSchedulerOperationState.ACCEPTED,
    ]
    assert f"--comment={scheduler_operations[0].marker}" in runner.calls[0][1]
    with pytest.raises(
        SlurmManifestError,
        match="requires one accepted scheduler operation",
    ):
        replace(
            manifest,
            scheduler_operations=(
                replace(
                    scheduler_operations[0],
                    state=SlurmSchedulerOperationState.UNKNOWN,
                ),
                *scheduler_operations[1:],
            ),
        )


def test_prepared_afterok_restart_discovers_lost_handle_and_continues_diamond(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_store(
        tmp_path,
        {
            "root": (),
            "left": ("root",),
            "right": ("root",),
            "join": ("left", "right"),
        },
        authority_backed=True,
    )
    planning = plan_afterok_slurm_dry_run(
        run_store=store,
        run_uri=run_uri,
        planning_id="queued-diamond",
        created_at="2026-08-30T00:00:00Z",
    )
    service = _started_service(tmp_path, clock=_clock("2026-08-30T00:00:00Z"))
    launch = prepared_slurm_launch(planning)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="diamond-item",
            queue_name="slurm",
            run_uri=run_uri,
            launch_contract=LaunchContract(
                adapter="slurm",
                entrypoint="prepared-run",
                snapshot=launch.to_snapshot(),
                delegated_verification={"shared_workspace": True},
            ),
        )
    )
    first_runner = FakeSlurmCommandRunner(
        scripted_results={
            "sbatch": [
                _sbatch_result("100"),
                _sbatch_result("101"),
                TimeoutError("response lost after scheduler acceptance"),
            ]
        }
    )
    QueueController(
        service,
        adapters={
            "slurm": SlurmQueueDispatchAdapter(
                command_runner=first_runner, run_store=store
            )
        },
    ).run_cycle(pool_name="slurm-pool")
    ambiguous = _live_manifest(store, run_uri)
    pending = cast(tuple[SlurmSchedulerOperation, ...], ambiguous.scheduler_operations)[
        -1
    ]
    assert pending.logical_key == "stage:right"
    assert pending.state is SlurmSchedulerOperationState.UNKNOWN

    recovery_runner = FakeSlurmCommandRunner(
        starting_job_id=103,
        scripted_results={
            "squeue": [
                SlurmCommandResult(
                    command="squeue",
                    argv=("squeue",),
                    returncode=0,
                    stdout=f"102|{pending.marker}\n",
                )
            ],
            "sacct": [SlurmCommandResult("sacct", ("sacct",), 0)],
        },
    )
    item = service.read_item("diamond-item")
    assert item is not None
    recovered = SlurmQueueDispatchAdapter(
        command_runner=recovery_runner, run_store=store
    ).dispatch(item)
    manifest = _live_manifest(store, run_uri)
    submitted = cast(tuple[SlurmSubmittedJob, ...], manifest.submitted_jobs)

    assert recovered.disposition == "started"
    assert [job.scheduler_job_id for job in submitted] == ["100", "101", "102", "103"]
    assert "--dependency=afterok:101:102" in recovery_runner.calls[-1][1]
    assert [
        operation.state
        for operation in cast(
            tuple[SlurmSchedulerOperation, ...], manifest.scheduler_operations
        )
    ] == [SlurmSchedulerOperationState.ACCEPTED] * 4


def test_prepared_restart_recovers_foreign_claim_after_handle_commit_loss(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_store(tmp_path, {"only": ()}, authority_backed=True)
    planning = plan_single_job_slurm_dry_run(
        run_store=store,
        run_uri=run_uri,
        planning_id="claimed-recovery",
        created_at="2026-08-30T00:00:00Z",
    )
    service = _started_service(tmp_path, clock=_clock("2026-08-30T00:00:00Z"))
    launch = prepared_slurm_launch(planning)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="claimed-item",
            queue_name="slurm",
            run_uri=run_uri,
            launch_contract=LaunchContract(
                adapter="slurm",
                entrypoint="prepared-run",
                snapshot=launch.to_snapshot(),
                delegated_verification={"shared_workspace": True},
            ),
        )
    )
    repository = cast(SQLiteQueueRepository, service.repository)
    queued = service.read_item("claimed-item")
    assert queued is not None
    claimed = repository._claim_selection_candidate(
        queued.queue_item_id,
        pool_name=queued.pool_name,
        expected_dispatch_attempt=queued.dispatch_attempt,
        owner_id="lost-driver",
        claim_id="lost-driver:claim:old-session:attempt",
        preference_id="test.lost_driver",
        reason_code="test.lost_driver",
    )
    assert claimed is not None
    lost = SlurmQueueDispatchAdapter(
        command_runner=FakeSlurmCommandRunner(
            scripted_results={"sbatch": [TimeoutError("lost scheduler response")]}
        ),
        run_store=store,
    ).dispatch(claimed)
    marker = cast(
        tuple[SlurmSchedulerOperation, ...],
        _live_manifest(store, run_uri).scheduler_operations,
    )[0].marker

    assert lost.reason_code == "slurm.prepared_submission_pending_reconciliation"
    assert service.read_item("claimed-item") == claimed

    recovery_runner = FakeSlurmCommandRunner(
        scripted_results={
            "squeue": [
                SlurmCommandResult(
                    "squeue",
                    ("squeue",),
                    0,
                    stdout=f"1900|{marker}\n",
                ),
                SlurmCommandResult(
                    "squeue",
                    ("squeue",),
                    0,
                    stdout="1900|RUNNING|None\n",
                ),
            ],
            "sacct": [
                SlurmCommandResult("sacct", ("sacct",), 0),
                SlurmCommandResult("sacct", ("sacct",), 0),
            ],
        }
    )
    recovered = QueueController(
        service,
        adapters={
            "slurm": SlurmQueueDispatchAdapter(
                command_runner=recovery_runner,
                run_store=store,
            )
        },
    ).drive_foreground(pool_name="slurm-pool", until_quiescent=True)
    item = service.read_item("claimed-item")

    assert len(recovered.cycles) == 2
    assert [
        step.outcome for step in recovered.cycles[0].reconciliation_steps
    ] == [
        "dispatched"
    ]
    assert [
        step.outcome for step in recovered.cycles[1].reconciliation_steps
    ] == ["handoff"]
    assert item is not None
    assert item.status is QueueItemStatus.DISPATCHED
    assert item.dispatch_handle is not None
    handoff = _mapping(item.dispatch_handle.evidence["delegated_handoff"])
    assert handoff["external_handle_persisted"] is True
    assert "scheduler_job_ids" not in item.dispatch_handle.evidence
    assert [call[0] for call in recovery_runner.calls] == [
        "squeue",
        "sacct",
        "sacct",
        "squeue",
    ]


def test_prepared_single_job_uses_the_same_manifest_owned_driver(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_store(tmp_path, {"only": ()}, authority_backed=True)
    planning = plan_single_job_slurm_dry_run(
        run_store=store,
        run_uri=run_uri,
        planning_id="queued-single",
        created_at="2026-08-30T00:00:00Z",
    )
    service = _started_service(tmp_path, clock=_clock("2026-08-30T00:00:00Z"))
    launch = prepared_slurm_launch(planning)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="single-item",
            queue_name="slurm",
            run_uri=run_uri,
            launch_contract=LaunchContract(
                adapter="slurm",
                entrypoint="prepared-run",
                snapshot=launch.to_snapshot(),
                delegated_verification={"shared_workspace": True},
            ),
        )
    )

    QueueController(
        service,
        adapters={
            "slurm": SlurmQueueDispatchAdapter(
                command_runner=FakeSlurmCommandRunner(starting_job_id=1500),
                run_store=store,
            )
        },
    ).run_cycle(pool_name="slurm-pool")
    manifest = _live_manifest(store, run_uri)

    assert manifest.mode == "slurm-single-job"
    assert manifest.queue_item_id == "single-item"
    assert [
        job.scheduler_job_id
        for job in cast(tuple[SlurmSubmittedJob, ...], manifest.submitted_jobs)
    ] == ["1500"]
    assert (
        cast(tuple[SlurmSchedulerOperation, ...], manifest.scheduler_operations)[
            0
        ].state
        is SlurmSchedulerOperationState.ACCEPTED
    )


def test_prepared_restart_never_replays_zero_or_multiple_marker_matches(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_store(tmp_path, {"only": ()}, authority_backed=True)
    planning = plan_afterok_slurm_dry_run(
        run_store=store,
        run_uri=run_uri,
        planning_id="queued-ambiguous",
        created_at="2026-08-30T00:00:00Z",
    )
    service = _started_service(tmp_path, clock=_clock("2026-08-30T00:00:00Z"))
    launch = prepared_slurm_launch(planning)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="ambiguous-item",
            queue_name="slurm",
            run_uri=run_uri,
            launch_contract=LaunchContract(
                adapter="slurm",
                entrypoint="prepared-run",
                snapshot=launch.to_snapshot(),
                delegated_verification={"shared_workspace": True},
            ),
        )
    )
    QueueController(
        service,
        adapters={
            "slurm": SlurmQueueDispatchAdapter(
                command_runner=FakeSlurmCommandRunner(
                    scripted_results={"sbatch": [TimeoutError("lost response")]}
                ),
                run_store=store,
            )
        },
    ).run_cycle(pool_name="slurm-pool")
    item = service.read_item("ambiguous-item")
    assert item is not None
    marker = cast(
        tuple[SlurmSchedulerOperation, ...],
        _live_manifest(store, run_uri).scheduler_operations,
    )[0].marker

    zero_runner = FakeSlurmCommandRunner(
        scripted_results={
            "sbatch": [AssertionError("ambiguous operation must not be replayed")]
        }
    )
    zero = SlurmQueueDispatchAdapter(
        command_runner=zero_runner, run_store=store
    ).dispatch(item)
    assert zero.reason_code == "slurm.prepared_submission_pending_reconciliation"
    assert zero.evidence["scheduler_operation_persisted"] is True
    assert "scheduler_job_ids" not in zero.evidence
    assert zero.evidence["delegated_handoff"] == {
        "durable": True,
        "external_handle_persisted": False,
        "downstream_status_read_succeeded": False,
        "persisted_downstream_status_read_succeeded": None,
        "authority_run_visibility_required": False,
        "loom_resource_leases_held": False,
    }
    assert [call[0] for call in zero_runner.calls] == ["squeue", "sacct"]

    conflict_runner = FakeSlurmCommandRunner(
        scripted_results={
            "squeue": [
                SlurmCommandResult("squeue", ("squeue",), 0, stdout=f"201|{marker}\n")
            ],
            "sacct": [
                SlurmCommandResult(
                    "sacct", ("sacct",), 0, stdout=f"202|{marker}|cluster-a\n"
                )
            ],
            "sbatch": [AssertionError("conflicting operation must not be replayed")],
        }
    )
    SlurmQueueDispatchAdapter(command_runner=conflict_runner, run_store=store).dispatch(
        item
    )
    operation = cast(
        tuple[SlurmSchedulerOperation, ...],
        _live_manifest(store, run_uri).scheduler_operations,
    )[0]
    assert operation.state is SlurmSchedulerOperationState.CONFLICT
    assert [call[0] for call in conflict_runner.calls] == ["squeue", "sacct"]

    retained = _live_manifest(store, run_uri)
    retained_operation = cast(
        tuple[SlurmSchedulerOperation, ...], retained.scheduler_operations
    )[0]
    submitted = store.latest_submitted_operation(run_uri)
    assert submitted is not None
    manifest_path = resolve_slurm_generated_artifact_path(
        store, run_uri, submitted.manifest_relative_path
    ).local_path
    write_slurm_live_manifest(
        manifest_path,
        replace(
            retained,
            scheduler_operations=(
                replace(
                    retained_operation,
                    marker="loom-op-v1:sha256:" + "0" * 64,
                ),
            ),
        ),
    )
    invalid_runner = FakeSlurmCommandRunner()
    invalid = SlurmQueueDispatchAdapter(
        command_runner=invalid_runner,
        run_store=store,
    ).dispatch(item)

    assert invalid.disposition == "not_started"
    assert invalid.reason_code == "slurm.prepared_submission_rejected"
    assert invalid_runner.calls == []


def test_prepared_inspection_uses_retained_failure_snapshot_when_accounting_is_pruned(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_store(tmp_path, {"only": ()}, authority_backed=True)
    planning = plan_afterok_slurm_dry_run(
        run_store=store,
        run_uri=run_uri,
        planning_id="retained-fact",
        created_at="2026-08-30T00:00:00Z",
    )
    service = _started_service(tmp_path, clock=_clock("2026-08-30T00:00:00Z"))
    launch = prepared_slurm_launch(planning)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="retained-item",
            queue_name="slurm",
            run_uri=run_uri,
            launch_contract=LaunchContract(
                adapter="slurm",
                entrypoint="prepared-run",
                snapshot=launch.to_snapshot(),
                delegated_verification={"shared_workspace": True},
            ),
        )
    )
    QueueController(
        service,
        adapters={
            "slurm": SlurmQueueDispatchAdapter(
                command_runner=FakeSlurmCommandRunner(starting_job_id=950),
                run_store=store,
            )
        },
    ).run_cycle(pool_name="slurm-pool")
    item = service.read_item("retained-item")
    operation = store.latest_submitted_operation(run_uri)
    assert item is not None and operation is not None
    observed = SlurmQueueDispatchAdapter(
        command_runner=FakeSlurmCommandRunner(
            scripted_results={
                "sacct": [
                    SlurmCommandResult(
                        "sacct", ("sacct",), 0, stdout="950|FAILED|1:0\\n"
                    )
                ]
            }
        ),
        run_store=store,
        clock=_clock("2026-08-30T00:01:00Z"),
    ).inspect(item)
    manifest = _live_manifest(store, run_uri)

    assert observed.terminal is True
    assert observed.status is QueueItemStatus.FAILED
    assert [
        snapshot.state
        for snapshot in cast(
            tuple[SlurmSchedulerStatusSnapshot, ...], manifest.status_snapshots
        )
    ] == ["FAILED"]

    inspection = SlurmQueueDispatchAdapter(
        command_runner=FakeSlurmCommandRunner(), run_store=store
    ).inspect(item)

    assert inspection.terminal is True
    assert inspection.status is QueueItemStatus.FAILED
    assert inspection.evidence["retained_scheduler_snapshots_used"] is True


@pytest.mark.parametrize(
    "shared_workspace",
    [
        None,
        False,
        {"status": "unproven"},
        {"status": "unsupported"},
        {"status": "proven", "extra": True},
        "proven",
    ],
)
def test_prepared_submission_requires_explicit_shared_workspace_proof(
    tmp_path: Path, shared_workspace: PlainData
) -> None:
    store, run_uri = _prepared_store(tmp_path, {"only": ()}, authority_backed=True)
    planning = plan_single_job_slurm_dry_run(
        run_store=store,
        run_uri=run_uri,
        planning_id="shared-workspace-proof",
        created_at="2026-08-30T00:00:00Z",
    )
    launch = prepared_slurm_launch(planning)
    runner = FakeSlurmCommandRunner()
    item = _prepared_queue_item(
        launch=launch,
        queue_item_id="proof-item",
        shared_workspace=shared_workspace,
    )

    rejected = SlurmQueueDispatchAdapter(
        command_runner=runner, run_store=store
    ).dispatch(item)

    assert rejected.disposition is QueueDispatchDisposition.NOT_STARTED
    assert rejected.reason_code == "slurm.prepared_shared_workspace_unproven"
    assert runner.calls == []


@pytest.mark.parametrize("shared_workspace", [True, {"status": "proven"}])
def test_prepared_submission_accepts_explicit_shared_workspace_proof(
    tmp_path: Path, shared_workspace: PlainData
) -> None:
    store, run_uri = _prepared_store(tmp_path, {"only": ()}, authority_backed=True)
    planning = plan_single_job_slurm_dry_run(
        run_store=store,
        run_uri=run_uri,
        planning_id="shared-workspace-proven",
        created_at="2026-08-30T00:00:00Z",
    )
    launch = prepared_slurm_launch(planning)
    runner = FakeSlurmCommandRunner()
    item = _prepared_queue_item(
        launch=launch,
        queue_item_id="proof-item",
        shared_workspace=shared_workspace,
    )

    accepted = SlurmQueueDispatchAdapter(
        command_runner=runner, run_store=store
    ).dispatch(item)

    assert accepted.disposition is QueueDispatchDisposition.STARTED
    assert [call[0] for call in runner.calls].count("sbatch") == 1


def test_prepared_inspection_never_promotes_scheduler_completion_to_run_success(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_store(tmp_path, {"only": ()}, authority_backed=True)
    planning = plan_single_job_slurm_dry_run(
        run_store=store,
        run_uri=run_uri,
        planning_id="authority-owner",
        created_at="2026-08-30T00:00:00Z",
    )
    service = _started_service(tmp_path, clock=_clock("2026-08-30T00:00:00Z"))
    launch = prepared_slurm_launch(planning)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="authority-item",
            queue_name="slurm",
            run_uri=run_uri,
            launch_contract=LaunchContract(
                adapter="slurm",
                entrypoint="prepared-run",
                snapshot=launch.to_snapshot(),
                delegated_verification={"shared_workspace": True},
            ),
        )
    )
    QueueController(
        service,
        adapters={
            "slurm": SlurmQueueDispatchAdapter(
                command_runner=FakeSlurmCommandRunner(starting_job_id=1800),
                run_store=store,
            )
        },
    ).run_cycle(pool_name="slurm-pool")
    item = service.read_item("authority-item")
    assert item is not None
    scheduler_complete = FakeSlurmCommandRunner(
        scripted_results={
            "sacct": [
                SlurmCommandResult(
                    "sacct",
                    ("sacct",),
                    0,
                    stdout="1800|COMPLETED|0:0\n",
                )
            ]
        }
    )

    settling = SlurmQueueDispatchAdapter(
        command_runner=scheduler_complete,
        run_store=store,
    ).inspect(item)

    assert settling.terminal is False
    assert settling.status is QueueItemStatus.DISPATCHED
    assert settling.handoff_complete is True
    assert "waiting for Loom run authority" in settling.reason

    store.write_run_status(
        run_uri,
        RunStatusRecord(
            run_uri=run_uri,
            status=RunStatus.SUCCEEDED,
            created_at="2026-08-30T00:00:00Z",
            updated_at="2026-08-30T00:10:00Z",
            started_at="2026-08-30T00:00:00Z",
            finished_at="2026-08-30T00:10:00Z",
        ),
    )
    pruned_runner = FakeSlurmCommandRunner()
    terminal = SlurmQueueDispatchAdapter(
        command_runner=pruned_runner,
        run_store=store,
    ).inspect(item)

    assert terminal.terminal is True
    assert terminal.status is QueueItemStatus.SUCCEEDED
    assert pruned_runner.calls == []


def test_prepared_inspection_uses_current_fact_per_handle_before_retained_fact(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_store(
        tmp_path, {"left": (), "right": ()}, authority_backed=True
    )
    planning = plan_afterok_slurm_dry_run(
        run_store=store,
        run_uri=run_uri,
        planning_id="current-per-handle",
        created_at="2026-08-30T00:00:00Z",
    )
    service = _started_service(tmp_path, clock=_clock("2026-08-30T00:00:00Z"))
    launch = prepared_slurm_launch(planning)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="current-per-handle-item",
            queue_name="slurm",
            run_uri=run_uri,
            launch_contract=LaunchContract(
                adapter="slurm",
                entrypoint="prepared-run",
                snapshot=launch.to_snapshot(),
                delegated_verification={"shared_workspace": True},
            ),
        )
    )
    QueueController(
        service,
        adapters={
            "slurm": SlurmQueueDispatchAdapter(
                command_runner=FakeSlurmCommandRunner(starting_job_id=1100),
                run_store=store,
            )
        },
    ).run_cycle(pool_name="slurm-pool")
    item = service.read_item("current-per-handle-item")
    assert item is not None
    manifest = _live_manifest(store, run_uri)
    jobs = cast(tuple[SlurmSubmittedJob, ...], manifest.submitted_jobs)
    manifest_path = resolve_slurm_generated_artifact_path(
        store, run_uri, manifest.manifest_relative_path
    ).local_path
    write_slurm_live_manifest(
        manifest_path,
        replace(
            manifest,
            status_snapshots=(
                SlurmSchedulerStatusSnapshot(
                    logical_key=jobs[0].logical_key,
                    scheduler_job_id=jobs[0].scheduler_job_id,
                    captured_at="2026-08-30T00:01:00Z",
                    source="sacct",
                    state="FAILED",
                    exit_code="1:0",
                ),
                SlurmSchedulerStatusSnapshot(
                    logical_key=jobs[1].logical_key,
                    scheduler_job_id=jobs[1].scheduler_job_id,
                    captured_at="2026-08-30T00:01:00Z",
                    source="sacct",
                    state="PENDING",
                ),
            ),
        ),
    )

    inspection = SlurmQueueDispatchAdapter(
        command_runner=FakeSlurmCommandRunner(
            scripted_results={
                "sacct": [
                    SlurmCommandResult(
                        "sacct",
                        ("sacct",),
                        0,
                        stdout=f"{jobs[0].scheduler_job_id}|COMPLETED|0:0\\n",
                    )
                ]
            }
        ),
        run_store=store,
        clock=_clock("2026-08-30T00:02:00Z"),
    ).inspect(item)

    assert inspection.terminal is False
    assert inspection.status is QueueItemStatus.DISPATCHED
    assert inspection.evidence["retained_scheduler_snapshots_used"] is True
    assert inspection.evidence["current_scheduler_facts_persisted"] == 1


def test_prepared_inspection_uses_retained_failure_for_missing_handle(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_store(
        tmp_path, {"left": (), "right": ()}, authority_backed=True
    )
    planning = plan_afterok_slurm_dry_run(
        run_store=store,
        run_uri=run_uri,
        planning_id="retained-missing-handle",
        created_at="2026-08-30T00:00:00Z",
    )
    service = _started_service(tmp_path, clock=_clock("2026-08-30T00:00:00Z"))
    launch = prepared_slurm_launch(planning)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="retained-missing-handle-item",
            queue_name="slurm",
            run_uri=run_uri,
            launch_contract=LaunchContract(
                adapter="slurm",
                entrypoint="prepared-run",
                snapshot=launch.to_snapshot(),
                delegated_verification={"shared_workspace": True},
            ),
        )
    )
    QueueController(
        service,
        adapters={
            "slurm": SlurmQueueDispatchAdapter(
                command_runner=FakeSlurmCommandRunner(starting_job_id=1200),
                run_store=store,
            )
        },
    ).run_cycle(pool_name="slurm-pool")
    item = service.read_item("retained-missing-handle-item")
    assert item is not None
    jobs = cast(
        tuple[SlurmSubmittedJob, ...],
        _live_manifest(store, run_uri).submitted_jobs,
    )
    first = SlurmQueueDispatchAdapter(
        command_runner=FakeSlurmCommandRunner(
            scripted_results={
                "sacct": [
                    SlurmCommandResult(
                        "sacct",
                        ("sacct",),
                        0,
                        stdout=(
                            f"{jobs[0].scheduler_job_id}|RUNNING|0:0\n"
                            f"{jobs[1].scheduler_job_id}|FAILED|1:0\n"
                        ),
                    )
                ]
            }
        ),
        run_store=store,
        clock=_clock("2026-08-30T00:01:00Z"),
    ).inspect(item)

    assert first.terminal is True
    assert first.status is QueueItemStatus.FAILED

    reopened = SlurmQueueDispatchAdapter(
        command_runner=FakeSlurmCommandRunner(
            scripted_results={
                "sacct": [
                    SlurmCommandResult(
                        "sacct",
                        ("sacct",),
                        0,
                        stdout=f"{jobs[0].scheduler_job_id}|RUNNING|0:0\n",
                    )
                ]
            }
        ),
        run_store=store,
        clock=_clock("2026-08-30T00:02:00Z"),
    ).inspect(item)

    assert reopened.terminal is True
    assert reopened.status is QueueItemStatus.FAILED
    assert reopened.evidence["retained_scheduler_snapshots_used"] is True
    assert reopened.evidence["current_scheduler_facts_persisted"] == 1


def test_prepared_inspection_requires_a_fact_for_every_completed_handle(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_store(
        tmp_path, {"left": (), "right": ()}, authority_backed=True
    )
    planning = plan_afterok_slurm_dry_run(
        run_store=store,
        run_uri=run_uri,
        planning_id="missing-completed-handle",
        created_at="2026-08-30T00:00:00Z",
    )
    service = _started_service(tmp_path, clock=_clock("2026-08-30T00:00:00Z"))
    launch = prepared_slurm_launch(planning)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="missing-completed-handle-item",
            queue_name="slurm",
            run_uri=run_uri,
            launch_contract=LaunchContract(
                adapter="slurm",
                entrypoint="prepared-run",
                snapshot=launch.to_snapshot(),
                delegated_verification={"shared_workspace": True},
            ),
        )
    )
    QueueController(
        service,
        adapters={
            "slurm": SlurmQueueDispatchAdapter(
                command_runner=FakeSlurmCommandRunner(starting_job_id=1300),
                run_store=store,
            )
        },
    ).run_cycle(pool_name="slurm-pool")
    item = service.read_item("missing-completed-handle-item")
    assert item is not None
    jobs = cast(
        tuple[SlurmSubmittedJob, ...],
        _live_manifest(store, run_uri).submitted_jobs,
    )

    inspection = SlurmQueueDispatchAdapter(
        command_runner=FakeSlurmCommandRunner(
            scripted_results={
                "sacct": [
                    SlurmCommandResult(
                        "sacct",
                        ("sacct",),
                        0,
                        stdout=f"{jobs[0].scheduler_job_id}|COMPLETED|0:0\n",
                    )
                ]
            }
        ),
        run_store=store,
        clock=_clock("2026-08-30T00:01:00Z"),
    ).inspect(item)

    assert inspection.terminal is False
    assert inspection.status is QueueItemStatus.DISPATCHED
    assert inspection.reason == "SLURM work remains active or is settling"
    assert inspection.evidence["retained_scheduler_snapshots_used"] is False
    assert inspection.evidence["current_scheduler_facts_persisted"] == 1


def test_service_less_driver_pages_many_active_and_queued_items(
    tmp_path: Path,
) -> None:
    service = _started_service(
        tmp_path,
        clock=_clock("2026-08-30T00:00:00Z"),
        max_dispatches_per_cycle=5,
    )
    for index in range(65):
        service.enqueue(_request(f"many-{index:03d}"))
    runner = FakeSlurmCommandRunner(starting_job_id=3000)

    result = QueueController(
        service,
        adapters={"slurm": SlurmQueueDispatchAdapter(command_runner=runner)},
    ).drive_foreground(pool_name="slurm-pool", until_quiescent=True)

    assert len(service.scan_recovery()) == 65
    assert [call[0] for call in runner.calls].count("sbatch") == 65
    assert max(len(cycle.dispatch_steps) for cycle in result.cycles) == 5
    assert all(len(cycle.reconciliation_steps) <= 32 for cycle in result.cycles)
    assert result.cycles[-1].reconciliation_pending is False


def _request(item_id: str) -> QueueEnqueueRequest:
    return QueueEnqueueRequest(
        queue_item_id=item_id,
        queue_name="slurm",
        run_uri=f"file:///runs/{item_id}",
        launch_contract=LaunchContract(
            adapter="slurm",
            entrypoint="sbatch",
            resources={"gpu": 1},
            snapshot={"script_path": f"/runs/{item_id}/slurm/job.sh"},
            delegated_verification={"shared_workspace": False},
        ),
    )


def _prepared_queue_item(
    *,
    launch: SlurmPreparedRunLaunch,
    queue_item_id: str,
    shared_workspace: PlainData,
) -> QueueItem:
    return QueueItem(
        queue_item_id=queue_item_id,
        queue_name="slurm",
        pool_name="slurm-pool",
        run_uri=launch.run_uri,
        run_intent=RunIntent(run_uri=launch.run_uri),
        launch_contract=LaunchContract(
            adapter="slurm",
            entrypoint="prepared-run",
            snapshot=launch.to_snapshot(),
            delegated_verification={"shared_workspace": shared_workspace},
        ),
        enqueued_at="2026-08-30T00:00:00Z",
        updated_at="2026-08-30T00:00:00Z",
    )


def _started_service(
    tmp_path: Path,
    *,
    clock,
    max_dispatches_per_cycle: int | None = None,
) -> QueueService:
    spec = normalize_queue_spec(
        {
            "schema_version": 2,
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [
                {
                    "pool_name": "slurm-pool",
                    "mode": "delegated",
                    "resources": {"gpu": 8},
                },
            ],
            "queues": [{"queue_name": "slurm", "pool_name": "slurm-pool"}],
            "controller": {
                "max_active_items": 1,
                "max_dispatches_per_cycle": max_dispatches_per_cycle,
            },
        }
    )
    service = QueueService(
        spec,
        SQLiteQueueRepository(tmp_path / "queue.sqlite", clock=clock),
        clock=clock,
    )
    service.start()
    return service


def _clock(*values: str):
    remaining = list(values)

    def next_value() -> str:
        if len(remaining) == 1:
            return remaining[0]
        return remaining.pop(0)

    return next_value


def _mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, Mapping)
    return cast(Mapping[str, object], value)


def _live_manifest(store, run_uri: str):
    operation = store.latest_submitted_operation(run_uri)
    assert operation is not None
    path = resolve_slurm_generated_artifact_path(
        store, run_uri, operation.manifest_relative_path
    ).local_path
    return read_slurm_live_manifest(json.loads(path.read_text(encoding="utf-8")))


def _sbatch_result(job_id: str) -> SlurmCommandResult:
    return SlurmCommandResult(
        command="sbatch",
        argv=("sbatch", "--parsable"),
        returncode=0,
        stdout=f"{job_id}\n",
    )


class _PersistCheckingRunner(FakeSlurmCommandRunner):
    def __init__(self, manifest_path: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self.manifest_path = manifest_path
        self.persisted_before_call_count = 0

    def sbatch(  # type: ignore[override]
        self,
        script_path,
        *,
        dependency_job_ids=(),
        comment=None,
        environment=None,
    ):
        manifest = read_slurm_live_manifest(
            json.loads(self.manifest_path.read_text(encoding="utf-8"))
        )
        operation = cast(
            tuple[SlurmSchedulerOperation, ...], manifest.scheduler_operations
        )[-1]
        assert operation.state is SlurmSchedulerOperationState.SUBMITTING
        assert operation.marker == comment
        assert operation.operation_id == operation.operation_digest
        self.persisted_before_call_count += 1
        return super().sbatch(
            script_path,
            dependency_job_ids=dependency_job_ids,
            comment=comment,
            environment=environment,
        )
