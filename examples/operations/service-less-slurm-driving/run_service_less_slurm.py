"""Drive two prepared SLURM runs across short-lived foreground processes."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from loom.pipeline.execution import (
    PREPARED_RUN_CONTINUATION_WHOLE_RUN,
    PREPARED_RUN_SCHEMA_VERSION,
    PreparedRunRecord,
    create_authority_backed_serial_run_store,
)
from loom.pipeline.executors.slurm.commands import (
    FakeSlurmCommandRunner,
)
from loom.pipeline.executors.slurm.planning import (
    plan_afterok_slurm_dry_run,
    plan_single_job_slurm_dry_run,
)
from loom.pipeline.planning import (
    ExecutionPlan,
    FingerprintContext,
    FingerprintStatus,
    PlanAction,
    PlanSelectors,
    ResumeOptions,
    StagePlan,
)
from loom.pipeline.status import RunStatus, RunStatusRecord
from loom.pipeline.stores import (
    AuthorityBackendKind,
    AuthorityConfig,
    AuthorityDeploymentProfile,
    path_to_run_uri,
)
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.queue import (
    LaunchContract,
    QueueController,
    QueueEnqueueRequest,
    QueueItemStatus,
    QueueService,
    SQLiteQueueRepository,
    normalize_queue_spec,
)
from loom.queue.slurm import SlurmQueueDispatchAdapter, prepared_slurm_launch


CREATED_AT = "2026-08-30T00:00:00Z"
FINISHED_AT = "2026-08-30T00:10:00Z"


def main() -> None:
    output_root = Path(
        os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", Path(__file__).resolve().parent)
    )
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    output_root.mkdir(parents=True, exist_ok=True)
    run_root.mkdir(parents=True, exist_ok=True)
    example_id = uuid4().hex[:8]
    queue_path = output_root / "queue.sqlite"

    authority_config = AuthorityConfig(
            backend_kind=AuthorityBackendKind.MANAGED_SERVICE,
            deployment_profile=AuthorityDeploymentProfile.MANAGED_SERVICE,
            endpoint="http://authority.invalid",
            workspace_id="service-less-example",
            reference_id=example_id,
    )
    single_store = create_authority_backed_serial_run_store(
        run_root,
        authority_store=SQLitePerRunAuthorityStore(),
        authority_config=authority_config,
    )
    afterok_store = create_authority_backed_serial_run_store(
        run_root,
        authority_store=SQLitePerRunAuthorityStore(),
        authority_config=authority_config,
    )
    single_uri = _prepare_run(
        single_store,
        run_root,
        run_name=f"single-{example_id}",
        executor_name="slurm-single-job",
        stage_upstreams={"pipeline": ()},
    )
    afterok_uri = _prepare_run(
        afterok_store,
        run_root,
        run_name=f"afterok-{example_id}",
        executor_name="slurm-afterok",
        stage_upstreams={"prepare": (), "finish": ("prepare",)},
    )
    single = plan_single_job_slurm_dry_run(
        run_store=single_store,
        run_uri=single_uri,
        planning_id=f"single-{example_id}",
        created_at=CREATED_AT,
    )
    afterok = plan_afterok_slurm_dry_run(
        run_store=afterok_store,
        run_uri=afterok_uri,
        planning_id=f"afterok-{example_id}",
        created_at=CREATED_AT,
    )

    spec = normalize_queue_spec(
        {
            "schema_version": 2,
            "db_path": str(queue_path),
            "pools": [{"pool_name": "slurm", "mode": "delegated"}],
            "queues": [{"queue_name": "slurm", "pool_name": "slurm"}],
            "controller": {"max_active_items": 1, "max_dispatches_per_cycle": 1},
        }
    )
    item_ids = (f"00-single-{example_id}", f"01-afterok-{example_id}")
    service = _open_service(spec, queue_path)
    for item_id, run_uri, planning in (
        (item_ids[0], single_uri, single),
        (item_ids[1], afterok_uri, afterok),
    ):
        launch = prepared_slurm_launch(planning)
        service.enqueue(
            QueueEnqueueRequest(
                queue_item_id=item_id,
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

    first_runner = FakeSlurmCommandRunner(starting_job_id=500)
    first_cycle = QueueController(
        service,
        adapters={
            "slurm": SlurmQueueDispatchAdapter(
                command_runner=first_runner,
                run_store=single_store,
            )
        },
    ).drive_foreground(pool_name="slurm", until_quiescent=False)
    _require_one_dispatch(first_cycle)
    service.stop()
    _write_run_status(single_store, single_uri, RunStatus.SUCCEEDED)

    reopened = _open_service(spec, queue_path)
    reconciliation = QueueController(
        reopened,
        adapters={
            "slurm": SlurmQueueDispatchAdapter(
                command_runner=FakeSlurmCommandRunner(),
                run_store=single_store,
            )
        },
    ).reconcile_current_session(pool_name="slurm")
    if [step.outcome for step in reconciliation.reconciliation_steps] != [
        "completed"
    ]:
        raise RuntimeError(
            f"expected the reopened driver to retain old completion: {reconciliation.to_dict()!r}"
        )
    second_runner = FakeSlurmCommandRunner(starting_job_id=600)
    reopened_cycle = QueueController(
        reopened,
        adapters={
            "slurm": SlurmQueueDispatchAdapter(
                command_runner=second_runner,
                run_store=afterok_store,
            )
        },
    ).drive_foreground(pool_name="slurm", until_quiescent=False)
    _require_one_dispatch(reopened_cycle)
    reopened.stop()

    _write_run_status(afterok_store, afterok_uri, RunStatus.SUCCEEDED)

    completed_service = _open_service(spec, queue_path)
    QueueController(
        completed_service,
        adapters={
            "slurm": SlurmQueueDispatchAdapter(
                command_runner=FakeSlurmCommandRunner(),
                run_store=afterok_store,
            )
        },
    ).drive_foreground(pool_name="slurm", until_quiescent=True)
    completed_items = [completed_service.read_item(item_id) for item_id in item_ids]
    completed_service.stop()

    scheduler_job_count = sum(
        call[0] == "sbatch" for call in (*first_runner.calls, *second_runner.calls)
    )
    print("service_less_slurm:")
    print("  prepared_runs: 2")
    print("  modes: slurm-single-job,slurm-afterok")
    print(f"  first_cycle_dispatched: {len(first_cycle.cycles[0].dispatch_steps)}")
    print(
        "  reopened_cycle_dispatched: "
        f"{len(reopened_cycle.cycles[0].dispatch_steps)}"
    )
    print(f"  scheduler_job_count: {scheduler_job_count}")
    print(
        "  completed_queue_items: "
        f"{sum(item is not None and item.status is QueueItemStatus.SUCCEEDED for item in completed_items)}"
    )
    print("  no_network_service: true")


def _prepare_run(
    run_store,
    run_root: Path,
    *,
    run_name: str,
    executor_name: str,
    stage_upstreams: dict[str, tuple[str, ...]],
) -> str:
    run_uri = path_to_run_uri(run_root / run_name)
    run_store.create_run(run_uri, metadata={"example": "service-less-slurm-driving"})
    plan = _execution_plan(run_uri, stage_upstreams)
    run_store.write_plan(run_uri, plan.to_dict())
    run_store.write_prepared_run(
        run_uri,
        PreparedRunRecord(
            schema_version=PREPARED_RUN_SCHEMA_VERSION,
            run_uri=run_uri,
            prepared_at=CREATED_AT,
            executor_name=executor_name,
            continuation_type=PREPARED_RUN_CONTINUATION_WHOLE_RUN,
            plan={"plan_summary": {"stage_count": len(stage_upstreams)}},
            config={"composition_manifest_ref": "config/composition_manifest.json"},
            runtime={"executor": executor_name, "stage_count": len(stage_upstreams)},
        ).to_dict(),
    )
    return run_uri


def _execution_plan(
    run_uri: str,
    stage_upstreams: dict[str, tuple[str, ...]],
) -> ExecutionPlan:
    stage_plans = tuple(
        StagePlan(
            stage_name=stage_name,
            action=PlanAction.RUN,
            base_action=PlanAction.RUN,
            fingerprint_status=FingerprintStatus.PENDING_INPUTS,
            fingerprint=None,
            resume_check=None,
            reasons=(),
            bound_inputs={},
            pending_inputs=(),
            reusable_outputs={},
            declared_outputs={},
            upstream_stages=upstream,
            downstream_stages=(),
            selected_by=(),
            invalidated_by=(),
        )
        for stage_name, upstream in stage_upstreams.items()
    )
    return ExecutionPlan(
        schema_version=1,
        run_uri=run_uri,
        pipeline_name="service-less-example",
        selectors=PlanSelectors(),
        resume=ResumeOptions(),
        fingerprint_context=FingerprintContext(
            python_version="3.12.0",
            loom_version="0.1.0",
        ),
        stage_order=tuple(stage_upstreams),
        stage_plans=stage_plans,
        reasons=(),
        summary={
            "RUN": len(stage_plans),
            "REUSE": 0,
            "SKIP": 0,
            "STALE": 0,
            "BLOCKED": 0,
        },
    )


def _open_service(spec, queue_path: Path) -> QueueService:
    service = QueueService(spec, SQLiteQueueRepository(queue_path))
    service.start()
    return service


def _require_one_dispatch(result) -> None:
    steps = result.cycles[0].dispatch_steps
    if len(steps) != 1 or steps[0].outcome != "dispatched":
        raise RuntimeError(f"expected one durable dispatch, got {result.to_dict()!r}")


def _write_run_status(run_store, run_uri: str, status: RunStatus) -> None:
    terminal = status is RunStatus.SUCCEEDED
    run_store.write_run_status(
        run_uri,
        RunStatusRecord(
            run_uri=run_uri,
            status=status,
            created_at=CREATED_AT,
            updated_at=FINISHED_AT if terminal else CREATED_AT,
            started_at=CREATED_AT,
            finished_at=FINISHED_AT if terminal else None,
            message=(
                "example compute work completed"
                if terminal
                else "example work accepted by the scheduler"
            ),
        ),
    )


if __name__ == "__main__":
    main()
