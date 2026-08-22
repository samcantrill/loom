from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from loom.pipeline.orchestration import (
    CoordinatorStoreError,
    InMemoryStageWorkStore,
    RunOrchestrator,
    SQLiteStageWorkStore,
)
from loom.pipeline.planning import (
    PLAN_SCHEMA_VERSION,
    ExecutionPlan,
    FingerprintContext,
    FingerprintStatus,
    PlanAction,
    PlanSelectors,
    ResumeOptions,
    StagePlan,
)
from loom.pipeline.resources import ResourceRequest
from loom.pipeline.runtime.placement import (
    StagePlacementPolicy,
    resolve_stage_placement,
)
from loom.pipeline.status import RunStatus
from loom.pipeline.status import StageStatus
from loom.pipeline.stores.authority import (
    PreparedAttemptReceipt,
    PreparedAttemptRequest,
)
from loom.scheduling import FifoSchedulingPolicy, SchedulingKernel
from tests.support.authority_stores import InMemoryPerRunAuthorityStore


def _stage(name: str, *, upstream: tuple[str, ...] = ()) -> StagePlan:
    return StagePlan(
        stage_name=name,
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


def _action_stage(
    name: str, action: PlanAction, *, upstream: tuple[str, ...] = ()
) -> StagePlan:
    stage = _stage(name, upstream=upstream)
    return StagePlan(
        stage_name=stage.stage_name,
        action=action,
        base_action=action,
        fingerprint_status=stage.fingerprint_status,
        fingerprint=stage.fingerprint,
        resume_check=stage.resume_check,
        reasons=stage.reasons,
        bound_inputs=stage.bound_inputs,
        pending_inputs=stage.pending_inputs,
        reusable_outputs=stage.reusable_outputs,
        declared_outputs=stage.declared_outputs,
        upstream_stages=stage.upstream_stages,
        downstream_stages=stage.downstream_stages,
        selected_by=stage.selected_by,
        invalidated_by=stage.invalidated_by,
    )


def _plan(run_uri: str, *stages: StagePlan) -> ExecutionPlan:
    return ExecutionPlan(
        schema_version=PLAN_SCHEMA_VERSION,
        run_uri=run_uri,
        pipeline_name="test",
        selectors=PlanSelectors(),
        resume=ResumeOptions(),
        fingerprint_context=FingerprintContext(),
        stage_order=tuple(stage.stage_name for stage in stages),
        stage_plans=tuple(stages),
        reasons=(),
        summary={"RUN": len(stages)},
    )


def _placement():
    return resolve_stage_placement(
        authored=ResourceRequest(),
        runtime=None,
        policy=StagePlacementPolicy(),
        planners={},
    )


def _authority(run_uri: str) -> InMemoryPerRunAuthorityStore:
    authority = InMemoryPerRunAuthorityStore()
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    return authority


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_reconcile_replays_exact_attempt_and_stable_stage_work(
    tmp_path: Path, kind: str
) -> None:
    run_uri = "file:///run"
    authority = _authority(run_uri)
    store = (
        InMemoryStageWorkStore()
        if kind == "memory"
        else SQLiteStageWorkStore(tmp_path / "stage-work.sqlite")
    )
    orchestrator = RunOrchestrator(
        authority=authority, store=store, owner_id="coordinator"
    )
    plan = _plan(run_uri, _stage("train"))
    initial = authority.open_run(run_uri)
    first = orchestrator.reconcile(
        admission_id="admission-1",
        plan=plan,
        authority_snapshot=initial,
        placements={"train": _placement()},
        ready_at=10,
    )[0]
    replay = orchestrator.reconcile(
        admission_id="admission-1",
        plan=plan,
        authority_snapshot=authority.open_run(run_uri),
        placements={"train": _placement()},
        ready_at=10,
    )[0]

    assert replay.stage_work_id == first.stage_work_id
    assert replay.attempt_id == first.attempt_id == "train-1"
    assert replay.projection_revision == 2
    assert len(authority.open_run(run_uri).stages[0].attempts) == 1
    assert store.list_stage_work() == (replay,)


def test_response_loss_after_authority_commit_replays_one_attempt(
    tmp_path: Path,
) -> None:
    run_uri = "file:///lost-reply"
    authority = _authority(run_uri)

    class LostReply:
        def __init__(self) -> None:
            self.drop = True

        def ensure_prepared_attempt(
            self, run_uri: str, request: PreparedAttemptRequest
        ) -> PreparedAttemptReceipt:
            receipt = authority.ensure_prepared_attempt(run_uri, request)
            if self.drop:
                self.drop = False
                raise RuntimeError("reply lost")
            return receipt

    store = SQLiteStageWorkStore(tmp_path / "coordinator.sqlite")
    orchestrator = RunOrchestrator(
        authority=LostReply(), store=store, owner_id="coordinator"
    )
    plan = _plan(run_uri, _stage("train"))
    snapshot = authority.open_run(run_uri)
    with pytest.raises(RuntimeError, match="reply lost"):
        orchestrator.reconcile(
            admission_id="admission-1",
            plan=plan,
            authority_snapshot=snapshot,
            placements={"train": _placement()},
            ready_at=10,
        )

    result = orchestrator.reconcile(
        admission_id="admission-1",
        plan=plan,
        authority_snapshot=authority.open_run(run_uri),
        placements={"train": _placement()},
        ready_at=10,
    )
    assert len(result) == 1
    assert len(authority.open_run(run_uri).stages[0].attempts) == 1
    assert len(store.list_stage_work()) == 1


def test_all_ready_branches_project_without_parallel_slot_suppression() -> None:
    run_uri = "file:///diamond"
    authority = _authority(run_uri)
    orchestrator = RunOrchestrator(
        authority=authority,
        store=InMemoryStageWorkStore(),
        owner_id="coordinator",
    )
    plan = _plan(run_uri, _stage("left"), _stage("right"))
    records = orchestrator.reconcile(
        admission_id="admission-1",
        plan=plan,
        authority_snapshot=authority.open_run(run_uri),
        placements={"left": _placement(), "right": _placement()},
        ready_at=10,
    )
    assert [record.stage_name for record in records] == ["left", "right"]
    assert [record.ready_order for record in records] == [0, 1]


def test_controller_actions_do_not_create_work_or_unlock_from_projection() -> None:
    run_uri = "file:///controller-actions"
    authority = _authority(run_uri)
    store = InMemoryStageWorkStore()
    orchestrator = RunOrchestrator(
        authority=authority, store=store, owner_id="coordinator"
    )
    actions: list[str] = []
    plan = _plan(
        run_uri,
        _action_stage("skip", PlanAction.SKIP),
        _stage("consume", upstream=("skip",)),
        _stage("independent"),
    )
    records = orchestrator.reconcile(
        admission_id="admission-1",
        plan=plan,
        authority_snapshot=authority.open_run(run_uri),
        placements={"consume": _placement(), "independent": _placement()},
        ready_at=10,
        controller_action=lambda stage, _readiness: actions.append(stage.stage_name),
    )
    assert actions == ["skip"]
    assert [record.stage_name for record in records] == ["independent"]


def test_stage_work_feeds_pure_kernel_without_reservation() -> None:
    run_uri = "file:///decision"
    authority = _authority(run_uri)
    orchestrator = RunOrchestrator(
        authority=authority,
        store=InMemoryStageWorkStore(),
        owner_id="coordinator",
    )
    orchestrator.reconcile(
        admission_id="admission-1",
        plan=_plan(run_uri, _stage("train")),
        authority_snapshot=authority.open_run(run_uri),
        placements={"train": _placement()},
        ready_at=10,
    )
    decision = orchestrator.decide(
        kernel=SchedulingKernel(
            planners={}, policy=FifoSchedulingPolicy()
        ),
        candidates=(),
        as_of=10,
    )
    assert decision.stage_work_id is None
    assert len(decision.work_evaluations) == 1


def test_authority_disagreement_makes_projection_ineligible() -> None:
    run_uri = "file:///authority-wins"
    authority = _authority(run_uri)
    store = InMemoryStageWorkStore()
    orchestrator = RunOrchestrator(
        authority=authority, store=store, owner_id="coordinator"
    )
    plan = _plan(run_uri, _stage("train"))
    orchestrator.reconcile(
        admission_id="admission-1",
        plan=plan,
        authority_snapshot=authority.open_run(run_uri),
        placements={"train": _placement()},
        ready_at=10,
    )
    authority.transition_stage(
        run_uri,
        "train",
        from_status=StageStatus.PENDING,
        to_status=StageStatus.CANCELLED,
    )
    assert (
        orchestrator.reconcile(
            admission_id="admission-1",
            plan=plan,
            authority_snapshot=authority.open_run(run_uri),
            placements={"train": _placement()},
            ready_at=10,
        )
        == ()
    )
    record = store.list_stage_work()[0]
    assert record.scheduling_state.value == "wait"
    decision = orchestrator.decide(
        kernel=SchedulingKernel(planners={}, policy=FifoSchedulingPolicy()),
        candidates=(),
        as_of=10,
    )
    assert decision.work_evaluations == ()


def test_sqlite_store_rejects_unsupported_schema_on_reopen(tmp_path: Path) -> None:
    path = tmp_path / "coordinator.sqlite"
    store = SQLiteStageWorkStore(path)
    assert store.list_stage_work() == ()
    # The first durable operation initializes the schema.
    run_uri = "file:///schema"
    authority = _authority(run_uri)
    RunOrchestrator(
        authority=authority, store=store, owner_id="coordinator"
    ).reconcile(
        admission_id="admission-1",
        plan=_plan(run_uri, _stage("train")),
        authority_snapshot=authority.open_run(run_uri),
        placements={"train": _placement()},
        ready_at=10,
    )
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE coordinator_metadata SET value = '99' WHERE key = 'schema_version'"
        )
    with pytest.raises(CoordinatorStoreError, match="unsupported"):
        SQLiteStageWorkStore(path).list_stage_work()
