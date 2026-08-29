from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline.orchestration import (
    CoordinatorStoreError,
    ExecutionRequirement,
    InMemoryStageWorkStore,
    RunOrchestrator,
    SchedulingProjectionState,
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
from loom.pipeline.reliability import (
    FailureClassification,
    ReliabilityStatusDetail,
    RetryDecisionRecord,
)
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
from loom.scheduling import (
    Candidate,
    FifoSchedulingPolicy,
    PolicyDecisionState,
    SchedulingKernel,
)
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


def _placement(*, pool_name: str = "default", target: str | None = None):
    return resolve_stage_placement(
        authored=ResourceRequest(),
        runtime=None,
        policy=StagePlacementPolicy(pool_name=pool_name, target=target),
        planners={},
    )


def _requirements(plan: ExecutionPlan) -> dict[str, ExecutionRequirement]:
    return {
        stage_name: ExecutionRequirement(
            "test-project", "test-environment", "test-executor"
        )
        for stage_name in plan.stage_order
    }


def _authority(run_uri: str) -> InMemoryPerRunAuthorityStore:
    authority = InMemoryPerRunAuthorityStore()
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    return authority


def _commit_stage(
    authority: InMemoryPerRunAuthorityStore,
    run_uri: str,
    stage_name: str,
    *,
    supersedes_commit_id: str | None = None,
):
    allocation = authority.allocate_stage_attempt(
        run_uri, stage_name, owner_id="worker", lease_ttl_seconds=30
    )
    assert allocation.lease is not None
    return authority.record_output_commit(
        run_uri,
        stage_name,
        attempt_id=allocation.attempt.attempt_id,
        fencing_token=allocation.lease.fencing_token,
        outputs={
            "out": ArtifactRef(
                artifact_id=f"{stage_name}/{allocation.attempt.attempt_id}",
                uri=f"{run_uri}/artifacts/{stage_name}/{allocation.attempt.attempt_id}",
                artifact_type="json",
            )
        },
        supersedes_commit_id=supersedes_commit_id,
    ).commit


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
        execution_requirements=_requirements(plan),
        ready_at=10,
    )[0]
    replay_store = (
        store
        if kind == "memory"
        else SQLiteStageWorkStore(tmp_path / "stage-work.sqlite")
    )
    replay = RunOrchestrator(
        authority=authority, store=replay_store, owner_id="coordinator"
    ).reconcile(
        admission_id="admission-1",
        plan=plan,
        authority_snapshot=authority.open_run(run_uri),
        placements={"train": _placement()},
        execution_requirements=_requirements(plan),
        ready_at=20,
    )[0]

    assert replay.stage_work_id == first.stage_work_id
    assert replay.attempt_id == first.attempt_id == "train-1"
    assert replay.ready_at == first.ready_at == 10
    assert replay.projection_revision == 2
    assert len(authority.open_run(run_uri).stages[0].attempts) == 1
    assert replay_store.list_stage_work() == (replay,)


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_reconcile_preserves_a_durable_decision_until_authority_changes(
    tmp_path: Path, kind: str
) -> None:
    run_uri = "file:///decided"
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
    initial = orchestrator.reconcile(
        admission_id="admission-1",
        plan=plan,
        authority_snapshot=authority.open_run(run_uri),
        placements={"train": _placement()},
        execution_requirements=_requirements(plan),
        ready_at=10,
    )[0]
    store.create_or_refresh(
        replace(
            initial,
            scheduling_state=SchedulingProjectionState.DECIDED,
            scheduling_diagnostics={"assignment_id": "assignment-1"},
        )
    )

    orchestrator.reconcile(
        admission_id="admission-1",
        plan=plan,
        authority_snapshot=authority.open_run(run_uri),
        placements={"train": _placement()},
        execution_requirements=_requirements(plan),
        ready_at=20,
    )
    retained = store.list_stage_work()[0]
    assert retained.scheduling_state is SchedulingProjectionState.DECIDED
    assert retained.scheduling_diagnostics == {"assignment_id": "assignment-1"}

    authority.transition_stage(
        run_uri,
        "train",
        from_status=StageStatus.PENDING,
        to_status=StageStatus.CANCELLED,
    )
    orchestrator.reconcile(
        admission_id="admission-1",
        plan=plan,
        authority_snapshot=authority.open_run(run_uri),
        placements={"train": _placement()},
        execution_requirements=_requirements(plan),
        ready_at=30,
    )
    assert store.list_stage_work()[0].scheduling_state is SchedulingProjectionState.WAIT


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
            execution_requirements=_requirements(plan),
            ready_at=10,
        )

    result = orchestrator.reconcile(
        admission_id="admission-1",
        plan=plan,
        authority_snapshot=authority.open_run(run_uri),
        placements={"train": _placement()},
        execution_requirements=_requirements(plan),
        ready_at=10,
    )
    assert len(result) == 1
    assert len(authority.open_run(run_uri).stages[0].attempts) == 1
    assert len(store.list_stage_work()) == 1


def test_intent_replays_before_first_attempt_after_authority_advances(
    tmp_path: Path,
) -> None:
    run_uri = "file:///intent-before-attempt"
    authority = _authority(run_uri)

    class LostBeforeCommit:
        def __init__(self) -> None:
            self.drop = True

        def ensure_prepared_attempt(
            self, run_uri: str, request: PreparedAttemptRequest
        ) -> PreparedAttemptReceipt:
            if self.drop:
                self.drop = False
                raise RuntimeError("request lost before authority commit")
            return authority.ensure_prepared_attempt(run_uri, request)

    store = SQLiteStageWorkStore(tmp_path / "coordinator.sqlite")
    orchestrator = RunOrchestrator(
        authority=LostBeforeCommit(), store=store, owner_id="coordinator"
    )
    plan = _plan(run_uri, _stage("left"), _stage("right"))
    with pytest.raises(RuntimeError, match="before authority commit"):
        orchestrator.reconcile(
            admission_id="admission-1",
            plan=plan,
            authority_snapshot=authority.open_run(run_uri),
            placements={"left": _placement(), "right": _placement()},
            execution_requirements=_requirements(plan),
            ready_at=10,
        )

    authority.allocate_stage_attempt(run_uri, "right", owner_id="worker")
    result = orchestrator.reconcile(
        admission_id="admission-1",
        plan=plan,
        authority_snapshot=authority.open_run(run_uri),
        placements={"left": _placement(), "right": _placement()},
        execution_requirements=_requirements(plan),
        ready_at=20,
    )

    assert [record.stage_name for record in result] == ["left"]
    left = next(
        stage
        for stage in authority.open_run(run_uri).stages
        if stage.stage_name == "left"
    )
    assert [attempt.attempt for attempt in left.attempts] == [1]
    assert len(store.list_stage_work()) == 1


def test_old_receipt_replay_does_not_regress_revision_for_new_retry() -> None:
    run_uri = "file:///replay-then-retry"
    authority = _authority(run_uri)
    allocation = authority.allocate_stage_attempt(run_uri, "right", owner_id="worker")
    authority.transition_stage(
        run_uri,
        "right",
        from_status=StageStatus.RUNNING,
        to_status=StageStatus.FAILED,
    )
    orchestrator = RunOrchestrator(
        authority=authority,
        store=InMemoryStageWorkStore(),
        owner_id="coordinator",
    )
    plan = _plan(run_uri, _stage("left"), _stage("right"))
    first = orchestrator.reconcile(
        admission_id="admission-1",
        plan=plan,
        authority_snapshot=authority.open_run(run_uri),
        placements={"left": _placement(), "right": _placement()},
        execution_requirements=_requirements(plan),
        ready_at=10,
    )
    assert [record.stage_name for record in first] == ["left"]

    status = ReliabilityStatusDetail(
        run_uri=run_uri,
        run_status=RunStatus.RUNNING,
        stage_id="right",
        stage_status=StageStatus.FAILED,
        attempt=1,
        created_at="2020-01-01T00:00:00Z",
    )
    authority.write_retry_decision(
        run_uri,
        RetryDecisionRecord(
            decision_id="retry-right",
            transaction_id="tx-right",
            should_retry=True,
            next_attempt=2,
            decision_reason="transient",
            policy_max_attempts=2,
            attempt_count=1,
            status=status,
            failure=FailureClassification(
                reason_code="runtime_error", status=status, retriable=True
            ),
        ),
    )
    second = orchestrator.reconcile(
        admission_id="admission-1",
        plan=plan,
        authority_snapshot=authority.open_run(run_uri),
        placements={"left": _placement(), "right": _placement()},
        execution_requirements=_requirements(plan),
        ready_at=10,
    )
    assert [record.stage_name for record in second] == ["left", "right"]
    assert second[1].attempt == allocation.attempt.attempt + 1


def test_retry_uses_a_new_intent_after_the_prior_attempt_was_projected() -> None:
    run_uri = "file:///projected-retry"
    authority = _authority(run_uri)
    store = InMemoryStageWorkStore()
    orchestrator = RunOrchestrator(
        authority=authority,
        store=store,
        owner_id="coordinator",
    )
    plan = _plan(run_uri, _stage("train"))
    first = orchestrator.reconcile(
        admission_id="admission-1",
        plan=plan,
        authority_snapshot=authority.open_run(run_uri),
        placements={"train": _placement()},
        execution_requirements=_requirements(plan),
        ready_at=10,
    )
    assert len(first) == 1
    assert first[0].attempt == 1
    authority.transition_stage(
        run_uri,
        "train",
        from_status=StageStatus.PENDING,
        to_status=StageStatus.FAILED,
    )
    status = ReliabilityStatusDetail(
        run_uri=run_uri,
        run_status=RunStatus.RUNNING,
        stage_id="train",
        stage_status=StageStatus.FAILED,
        attempt=1,
        created_at="2020-01-01T00:00:00Z",
    )
    authority.write_retry_decision(
        run_uri,
        RetryDecisionRecord(
            decision_id="retry-train",
            transaction_id="tx-train",
            should_retry=True,
            next_attempt=2,
            decision_reason="transient",
            policy_max_attempts=2,
            attempt_count=1,
            status=status,
            failure=FailureClassification(
                reason_code="runtime_error", status=status, retriable=True
            ),
        ),
    )

    second = orchestrator.reconcile(
        admission_id="admission-1",
        plan=plan,
        authority_snapshot=authority.open_run(run_uri),
        placements={"train": _placement()},
        execution_requirements=_requirements(plan),
        ready_at=11,
    )

    assert len(second) == 1
    assert second[0].attempt == 2
    assert {item.attempt for item in store.list_stage_work()} == {1, 2}


def test_replay_rejects_equal_revision_sequence_with_changed_token() -> None:
    run_uri = "file:///revision-token-conflict"
    authority = _authority(run_uri)
    orchestrator = RunOrchestrator(
        authority=authority,
        store=InMemoryStageWorkStore(),
        owner_id="coordinator",
    )
    plan = _plan(run_uri, _stage("train"))
    orchestrator.reconcile(
        admission_id="admission-1",
        plan=plan,
        authority_snapshot=authority.open_run(run_uri),
        placements={"train": _placement()},
        execution_requirements=_requirements(plan),
        ready_at=10,
    )
    snapshot = authority.open_run(run_uri)
    conflicting = replace(
        snapshot,
        revision=replace(snapshot.revision, token="conflicting-revision-token"),
    )

    with pytest.raises(CoordinatorStoreError, match="without monotonic progress"):
        orchestrator.reconcile(
            admission_id="admission-1",
            plan=plan,
            authority_snapshot=conflicting,
            placements={"train": _placement()},
            execution_requirements=_requirements(plan),
            ready_at=20,
        )


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
        execution_requirements=_requirements(plan),
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
        execution_requirements=_requirements(plan),
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
        execution_requirements=_requirements(_plan(run_uri, _stage("train"))),
        ready_at=10,
    )
    decision = orchestrator.decide(
        kernel=SchedulingKernel(planners={}, policy=FifoSchedulingPolicy()),
        candidates=(),
        as_of=10,
    )
    assert decision.stage_work_id is None
    assert len(decision.work_evaluations) == 1


def test_decision_can_be_scoped_to_one_admission() -> None:
    first_uri = "file:///decision-first"
    second_uri = "file:///decision-second"
    store = InMemoryStageWorkStore()
    first_authority = _authority(first_uri)
    second_authority = _authority(second_uri)
    first = RunOrchestrator(
        authority=first_authority, store=store, owner_id="coordinator"
    )
    second = RunOrchestrator(
        authority=second_authority, store=store, owner_id="coordinator"
    )
    first.reconcile(
        admission_id="admission-first",
        plan=_plan(first_uri, _stage("first")),
        authority_snapshot=first_authority.open_run(first_uri),
        placements={"first": _placement()},
        execution_requirements=_requirements(_plan(first_uri, _stage("first"))),
        ready_at=10,
    )
    second.reconcile(
        admission_id="admission-second",
        plan=_plan(second_uri, _stage("second")),
        authority_snapshot=second_authority.open_run(second_uri),
        placements={"second": _placement()},
        execution_requirements=_requirements(_plan(second_uri, _stage("second"))),
        ready_at=11,
    )

    decision = second.decide(
        kernel=SchedulingKernel(planners={}, policy=FifoSchedulingPolicy()),
        candidates=(),
        as_of=11,
        admission_id="admission-second",
    )

    assert [item.stage_work_id for item in decision.work_evaluations] == [
        store.list_stage_work()[1].stage_work_id
    ]


def test_resolved_pool_and_target_reach_mandatory_kernel_eligibility() -> None:
    run_uri = "file:///placement-decision"
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
        placements={"train": _placement(pool_name="pool-b", target="machine-b")},
        execution_requirements=_requirements(_plan(run_uri, _stage("train"))),
        ready_at=10,
    )

    decision = orchestrator.decide(
        kernel=SchedulingKernel(planners={}, policy=FifoSchedulingPolicy()),
        candidates=(
            Candidate("machine-0", {}, {}, pool_names=("pool-a",)),
            Candidate("machine-a", {}, {}, pool_names=("pool-b",)),
            Candidate("machine-b", {}, {}, pool_names=("pool-b",)),
        ),
        as_of=10,
    )

    assert decision.state is PolicyDecisionState.SELECT
    assert decision.candidate_id == "machine-b"


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
        execution_requirements=_requirements(plan),
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
            execution_requirements=_requirements(plan),
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


def test_run_cancellation_retires_pending_ready_projection() -> None:
    run_uri = "file:///cancelled-run"
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
        execution_requirements=_requirements(plan),
        ready_at=10,
    )
    assert (
        orchestrator.decide(
            kernel=SchedulingKernel(planners={}, policy=FifoSchedulingPolicy()),
            candidates=(Candidate("machine-a", {}, {}),),
            as_of=10,
        ).state
        is PolicyDecisionState.SELECT
    )

    authority.transition_run(
        run_uri, from_status=RunStatus.RUNNING, to_status=RunStatus.CANCELLED
    )
    assert (
        orchestrator.reconcile(
            admission_id="admission-1",
            plan=plan,
            authority_snapshot=authority.open_run(run_uri),
            placements={"train": _placement()},
            execution_requirements=_requirements(plan),
            ready_at=20,
        )
        == ()
    )
    assert store.list_stage_work()[0].scheduling_state.value == "wait"
    assert (
        orchestrator.decide(
            kernel=SchedulingKernel(planners={}, policy=FifoSchedulingPolicy()),
            candidates=(Candidate("machine-a", {}, {}),),
            as_of=20,
        ).work_evaluations
        == ()
    )


def test_superseded_upstream_commit_retires_pending_ready_projection() -> None:
    run_uri = "file:///superseded-upstream"
    authority = _authority(run_uri)
    first_commit = _commit_stage(authority, run_uri, "source")
    store = InMemoryStageWorkStore()
    orchestrator = RunOrchestrator(
        authority=authority, store=store, owner_id="coordinator"
    )
    plan = _plan(run_uri, _stage("source"), _stage("train", upstream=("source",)))
    first = orchestrator.reconcile(
        admission_id="admission-1",
        plan=plan,
        authority_snapshot=authority.open_run(run_uri),
        placements={"source": _placement(), "train": _placement()},
        execution_requirements=_requirements(plan),
        ready_at=10,
    )
    assert [record.stage_name for record in first] == ["train"]
    assert first[0].upstream_commits == {"source": first_commit.commit_id}

    replacement = _commit_stage(
        authority,
        run_uri,
        "source",
        supersedes_commit_id=first_commit.commit_id,
    )
    assert replacement.commit_id != first_commit.commit_id
    assert (
        orchestrator.reconcile(
            admission_id="admission-1",
            plan=plan,
            authority_snapshot=authority.open_run(run_uri),
            placements={"source": _placement(), "train": _placement()},
            execution_requirements=_requirements(plan),
            ready_at=20,
        )
        == ()
    )
    record = store.list_stage_work()[0]
    assert record.upstream_commits == {"source": first_commit.commit_id}
    assert record.scheduling_state.value == "wait"


def test_sqlite_store_rejects_unsupported_schema_on_reopen(tmp_path: Path) -> None:
    path = tmp_path / "coordinator.sqlite"
    store = SQLiteStageWorkStore(path)
    assert store.list_stage_work() == ()
    # The first durable operation initializes the schema.
    run_uri = "file:///schema"
    authority = _authority(run_uri)
    RunOrchestrator(authority=authority, store=store, owner_id="coordinator").reconcile(
        admission_id="admission-1",
        plan=_plan(run_uri, _stage("train")),
        authority_snapshot=authority.open_run(run_uri),
        placements={"train": _placement()},
        execution_requirements=_requirements(_plan(run_uri, _stage("train"))),
        ready_at=10,
    )
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE coordinator_metadata SET value = '99' WHERE key = 'schema_version'"
        )
    with pytest.raises(CoordinatorStoreError, match="unsupported"):
        SQLiteStageWorkStore(path).list_stage_work()


def test_257_stage_pipeline_drains_across_bounded_ready_windows(
    tmp_path: Path,
) -> None:
    run_uri = "file:///ready-window"
    authority = _authority(run_uri)
    store = SQLiteStageWorkStore(tmp_path / "coordinator.sqlite")
    stages = tuple(_stage(f"stage-{index:03d}") for index in range(257))
    plan = _plan(run_uri, *stages)
    records = RunOrchestrator(
        authority=authority, store=store, owner_id="coordinator"
    ).reconcile(
        admission_id="admission-1",
        plan=plan,
        authority_snapshot=authority.open_run(run_uri),
        placements={stage.stage_name: _placement() for stage in stages},
        execution_requirements=_requirements(plan),
        ready_at=10,
        run_priority=9,
        enqueue_sequence=3,
    )

    assert len(records) == 257
    window = store.ready_window()
    assert len(window) == 256
    assert [record.stage_name for record in window] == [
        f"stage-{index:03d}" for index in range(256)
    ]
    assert (
        store.ready_window(limit=1)[0].to_work_item().order_key.negative_priority == -9
    )
    assert store.ready_window(limit=256)[-1].enqueue_sequence == 3
    for record in window:
        store.create_or_refresh(
            replace(record, scheduling_state=SchedulingProjectionState.DECIDED)
        )
    final_window = store.ready_window()
    assert [record.stage_name for record in final_window] == ["stage-256"]
    store.create_or_refresh(
        replace(final_window[0], scheduling_state=SchedulingProjectionState.DECIDED)
    )
    assert store.ready_window() == ()


def test_ready_window_preserves_fifo_admission_order_after_restart(
    tmp_path: Path,
) -> None:
    path = tmp_path / "coordinator.sqlite"
    store = SQLiteStageWorkStore(path)
    for suffix, enqueue_sequence, ready_at in (
        ("older", 1, 20),
        ("newer", 2, 10),
    ):
        run_uri = f"file:///{suffix}"
        authority = _authority(run_uri)
        RunOrchestrator(
            authority=authority,
            store=store,
            owner_id="coordinator",
        ).reconcile(
            admission_id=f"admission-{suffix}",
            plan=_plan(run_uri, _stage(suffix)),
            authority_snapshot=authority.open_run(run_uri),
            placements={suffix: _placement()},
            execution_requirements=_requirements(_plan(run_uri, _stage(suffix))),
            ready_at=ready_at,
            run_priority=4,
            enqueue_sequence=enqueue_sequence,
        )

    reopened = SQLiteStageWorkStore(path, _allow_initialize=False)
    assert [record.stage_name for record in reopened.ready_window()] == [
        "older",
        "newer",
    ]


def test_stage_work_hard_cut_requires_durable_global_order_fields() -> None:
    run_uri = "file:///order-fields"
    authority = _authority(run_uri)
    store = InMemoryStageWorkStore()
    record = RunOrchestrator(
        authority=authority, store=store, owner_id="coordinator"
    ).reconcile(
        admission_id="admission-1",
        plan=_plan(run_uri, _stage("train")),
        authority_snapshot=authority.open_run(run_uri),
        placements={"train": _placement()},
        execution_requirements=_requirements(_plan(run_uri, _stage("train"))),
        ready_at=10,
        run_priority=5,
        enqueue_sequence=7,
    )[0]
    payload = record.to_dict()
    del payload["run_priority"]

    with pytest.raises(CoordinatorStoreError, match="fields are invalid"):
        type(record).from_dict(payload)
