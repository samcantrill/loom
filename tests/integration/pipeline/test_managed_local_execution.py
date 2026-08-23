"""Integration coverage for the durable embedded local stage saga."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
from typing import Never

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline import OutputSpec, PipelineSpec, StageFactorySpec, StageSpec
from loom.pipeline.execution import prepare_stage_attempt
from loom.pipeline.execution.managed_local import (
    AssignmentState,
    AtomResourceProvider,
    ClaimCommand,
    ManagedAssignment,
    ManagedLocalError,
    ManagedOfferSnapshot,
    ManagedProcessStartError,
    ObserveRequest,
    SQLiteAgentJournal,
    SQLiteCoordinatorAssignments,
    run_managed_local_assignment,
)
from loom.pipeline.execution.models import StageWorkerResult
from loom.pipeline.orchestration import (
    SQLiteStageWorkStore,
    StageWorkRecord,
    stage_work_identity,
)
from loom.pipeline.planning import plan_pipeline
from loom.pipeline.resources import ResourceRequest
from loom.pipeline.runtime import ResolvedStageRuntimeOptions
from loom.pipeline.runtime.placement import (
    StagePlacementPolicy,
    resolve_stage_placement,
)
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import (
    BackendRevision,
    LocalArtifactStore,
    LocalRunStore,
    PreparedAttemptRequest,
    path_to_run_uri,
)
from loom.pipeline.stores.authority import OutputCommit
from loom.pipeline.stores.read_models import LifecycleReason
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.scheduling import (
    CapacityAtom,
    ExactQuantity,
    ResourceClaim,
    ResourceClaimContractDescriptor,
    SchedulingComponentDescriptor,
)
from loom.serialization import PlainData


pytestmark = pytest.mark.integration


class _CommitThenTimeoutAuthority(SQLitePerRunAuthorityStore):
    def __init__(self) -> None:
        super().__init__(clock=lambda: "2020-01-01T00:00:00Z")
        self._timeout_once = True

    def record_output_commit(
        self,
        run_uri: str,
        stage_name: str,
        *,
        attempt_id: str,
        fencing_token: str,
        outputs: Mapping[str, ArtifactRef],
        supersedes_commit_id: str | None = None,
        reason: LifecycleReason | None = None,
        assignment_id: str | None = None,
    ) -> OutputCommit:
        result = super().record_output_commit(
            run_uri,
            stage_name,
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            outputs=outputs,
            supersedes_commit_id=supersedes_commit_id,
            reason=reason,
            assignment_id=assignment_id,
        )
        if self._timeout_once:
            self._timeout_once = False
            raise TimeoutError("output commit response was lost")
        return result


class _UnbindThenTimeoutAuthority(SQLitePerRunAuthorityStore):
    def __init__(self) -> None:
        super().__init__(clock=lambda: "2020-01-01T00:00:00Z")
        self._timeout_once = True

    def unbind_prepared_attempt(
        self, run_uri: str, *, assignment_id: str, attempt_id: str
    ) -> None:
        super().unbind_prepared_attempt(
            run_uri,
            assignment_id=assignment_id,
            attempt_id=attempt_id,
        )
        if self._timeout_once:
            self._timeout_once = False
            raise TimeoutError("unbind response was lost")


def _definitive_start_failure_launcher(
    process_execution_id: str,
    worker: Callable[[], StageWorkerResult],
) -> Never:
    del process_execution_id, worker
    raise ManagedProcessStartError("managed root was not created")


def _spec(*, counter_path: Path | None = None) -> PipelineSpec:
    return PipelineSpec.from_config(
        {
            "name": "managed-local",
            "stages": [
                {
                    "name": "build",
                    "factory": {
                        "_target_": (
                            "tests.support.pipeline_execution_stages.JsonProducerStage"
                        )
                    },
                    "config": {
                        "value": 42,
                        **(
                            {}
                            if counter_path is None
                            else {"counter_path": str(counter_path)}
                        ),
                    },
                    "outputs": {
                        "data": {
                            "artifact_type": "json",
                            "codec_key": "json.v1",
                        }
                    },
                }
            ],
        }
    )


def _seed_stage_work(
    path: Path,
    assignment: ManagedAssignment,
    *,
    admission_id: str,
    readiness_generation: str,
    plan_fingerprint: str,
    authority_revision: BackendRevision,
) -> None:
    SQLiteStageWorkStore(path).create_or_refresh(
        StageWorkRecord(
            stage_work_id=assignment.stage_work_id,
            admission_id=admission_id,
            run_uri=assignment.run_uri,
            stage_name=assignment.stage_name,
            attempt=assignment.attempt,
            attempt_id=assignment.attempt_id,
            readiness_generation=readiness_generation,
            ready_at=1,
            ready_order=1,
            plan_fingerprint=plan_fingerprint,
            authority_revision=authority_revision,
            bound_inputs={},
            upstream_commits={},
            placement=resolve_stage_placement(
                authored=ResourceRequest(),
                runtime=None,
                policy=StagePlacementPolicy(),
                planners={},
            ),
        )
    )


def _decision_receipt(
    assignment: ManagedAssignment,
    claim: ResourceClaim,
    descriptor: SchedulingComponentDescriptor,
) -> dict[str, PlainData]:
    return {
        "policy_epoch": "policy-1",
        "policy_descriptor": {"name": "fifo", "version": 1},
        "stage_work_id": assignment.stage_work_id,
        "candidate_id": assignment.agent_id,
        "stage_work_revision": 1,
        "snapshot_revision": "snapshot-1",
        "offer_revision": assignment.offer_id,
        "score_summary": {"tiers": [0]},
        "fallback_eligible": False,
        "as_of": "2020-01-01T00:00:00Z",
        "reason_codes": ["selected"],
        "component_descriptors": [descriptor.to_dict()],
        "claim_contract_descriptors": [claim.contract.to_dict()],
    }


def _offer_snapshot(
    assignment: ManagedAssignment,
    descriptor: SchedulingComponentDescriptor,
    atoms: tuple[CapacityAtom, ...],
    *,
    availability_revision: str,
    reflected_claim_ids: tuple[str, ...] = (),
) -> ManagedOfferSnapshot:
    return ManagedOfferSnapshot(
        agent_id=assignment.agent_id,
        session_id=assignment.session_id,
        offer_revision=assignment.offer_id,
        snapshot_revision="snapshot-1",
        inventory_revision="inventory-1",
        availability_revision=availability_revision,
        component_descriptors=(descriptor,),
        atoms=atoms,
        reflected_claim_ids=reflected_claim_ids,
    )


def test_managed_local_assignment_commits_accessible_output_then_releases(
    tmp_path: Path,
) -> None:
    run_store = LocalRunStore(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "run-1")
    run_store.create_run(run_uri)
    counter_path = tmp_path / "launch-count.txt"
    spec = _spec(counter_path=counter_path)
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=run_store,
        artifact_store=LocalArtifactStore(run_store.local_artifact_root(run_uri)),
        persist=True,
    )
    worker_request = prepare_stage_attempt(
        run_store=run_store,
        run_uri=run_uri,
        stage=spec.get_stage("build"),
        stage_plan=plan.ordered_stage_plans[0],
        resolved_runtime=ResolvedStageRuntimeOptions(
            stage_id="build", executor="local"
        ),
    )

    authority = _CommitThenTimeoutAuthority()
    revision = authority.create_run(run_uri)
    prepared = authority.ensure_prepared_attempt(
        run_uri,
        PreparedAttemptRequest(
            operation_id="prepare-build-1",
            request_digest="digest-build-1",
            admission_id="admission-1",
            stage_name="build",
            readiness_generation="ready-build-1",
            expected_revision=revision,
            expected_stage_status=None,
            expected_attempt_id=None,
            next_attempt=1,
            owner_id="coordinator",
            plan_fingerprint="plan-1",
            bound_inputs={},
            upstream_commits={},
        ),
    )
    assert worker_request.attempt == prepared.attempt.attempt

    atom = CapacityAtom("cpu", "cpu-0", ExactQuantity(2), "count", ExactQuantity(1))
    contract = ResourceClaimContractDescriptor("cpu", 1, "cpu-contract")
    claim = ResourceClaim("cpu", contract, (atom,), 1)
    readiness_generation = "ready-build-1"
    assignment = ManagedAssignment(
        assignment_id="assignment-build-1",
        run_uri=run_uri,
        stage_work_id=stage_work_identity(
            "admission-1",
            "build",
            prepared.attempt.attempt_id,
            readiness_generation,
        ),
        stage_name="build",
        attempt=prepared.attempt.attempt,
        attempt_id=prepared.attempt.attempt_id,
        agent_id="agent-local",
        session_id="session-1",
        offer_id="offer-1",
        claim_id="claim-build-1",
    )
    descriptor = SchedulingComponentDescriptor(
        "cpu", 1, "1", "cpu-provider", "configured"
    )
    provider = AtomResourceProvider(descriptor, (contract,), (atom,))
    command = ClaimCommand(assignment, "claim-build-1:prepare", claim)
    coordinator_path = tmp_path / "coordinator" / "state.sqlite"
    _seed_stage_work(
        coordinator_path,
        assignment,
        admission_id="admission-1",
        readiness_generation=readiness_generation,
        plan_fingerprint="plan-1",
        authority_revision=prepared.attempt.revision,
    )
    coordinator = SQLiteCoordinatorAssignments(coordinator_path, (atom,))
    coordinator.publish_offer(
        _offer_snapshot(
            assignment,
            descriptor,
            (atom,),
            availability_revision="availability-initial",
        )
    )
    journal = SQLiteAgentJournal(tmp_path / "agent" / "journal.sqlite")

    def execute():
        return run_managed_local_assignment(
            coordinator=coordinator,
            authority=authority,
            journal=journal,
            assignment=assignment,
            worker_request=worker_request,
            claims=(claim,),
            commands=(command,),
            providers={"cpu": provider},
            run_store=run_store,
            max_parallel_stages=1,
            decision_receipt=_decision_receipt(assignment, claim, descriptor),
        )

    with pytest.raises(TimeoutError, match="response was lost"):
        execute()
    assert authority.snapshot(run_uri).stages[0].status is StageStatus.SUCCEEDED
    assert coordinator.state(assignment.assignment_id) == "running"
    assert (
        journal.read_state(assignment.assignment_id) is AssignmentState.RESULT_DURABLE
    )

    receipt = execute()
    replay = execute()

    assert receipt.worker_result.status is StageStatus.SUCCEEDED
    assert replay == receipt
    assert counter_path.read_text(encoding="utf-8") == "1"
    assert receipt.output_commit is not None
    artifact = receipt.worker_result.outputs["data"]
    assert LocalArtifactStore(run_store.local_artifact_root(run_uri)).load(
        artifact
    ) == {"value": 42}
    snapshot = authority.snapshot(run_uri)
    assert snapshot.stages[0].status is StageStatus.SUCCEEDED
    assert snapshot.stages[0].latest_commit == receipt.output_commit.commit
    assert coordinator.state(assignment.assignment_id) == "released"
    assert journal.read_state(assignment.assignment_id).value == "released"
    assert run_store.read_stage_outputs(run_uri, "build") is None
    observed = provider.observe(
        ObserveRequest("agent-local", "session-1", "observe-after-release")
    )
    assert observed.atoms == (atom,)
    assert observed.live_claim_ids == ()


@pytest.mark.parametrize("failure_mode", ["worker", "start"])
def test_managed_local_failure_terminalizes_before_capacity_release(
    tmp_path: Path, failure_mode: str
) -> None:
    run_store = LocalRunStore(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "failed-run")
    run_store.create_run(run_uri)
    spec = (
        PipelineSpec.from_config(
            {
                "name": "managed-local-failure",
                "stages": [
                    {
                        "name": "build",
                        "factory": {
                            "_target_": (
                                "tests.support.pipeline_execution_stages.FailingStage"
                            )
                        },
                        "outputs": {
                            "data": {
                                "artifact_type": "json",
                                "codec_key": "json.v1",
                            }
                        },
                    }
                ],
            }
        )
        if failure_mode == "worker"
        else _spec()
    )
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=run_store,
        artifact_store=LocalArtifactStore(run_store.local_artifact_root(run_uri)),
        persist=True,
    )
    worker_request = prepare_stage_attempt(
        run_store=run_store,
        run_uri=run_uri,
        stage=spec.get_stage("build"),
        stage_plan=plan.ordered_stage_plans[0],
        resolved_runtime=ResolvedStageRuntimeOptions(
            stage_id="build", executor="local"
        ),
    )
    authority = SQLitePerRunAuthorityStore(clock=lambda: "2020-01-01T00:00:00Z")
    revision = authority.create_run(run_uri)
    readiness_generation = "ready-build-failed"
    prepared = authority.ensure_prepared_attempt(
        run_uri,
        PreparedAttemptRequest(
            operation_id="prepare-build-failed",
            request_digest="digest-build-failed",
            admission_id="admission-failed",
            stage_name="build",
            readiness_generation=readiness_generation,
            expected_revision=revision,
            expected_stage_status=None,
            expected_attempt_id=None,
            next_attempt=1,
            owner_id="coordinator",
            plan_fingerprint="plan-failed",
            bound_inputs={},
            upstream_commits={},
        ),
    )
    assignment = ManagedAssignment(
        assignment_id="assignment-build-failed",
        run_uri=run_uri,
        stage_work_id=stage_work_identity(
            "admission-failed",
            "build",
            prepared.attempt.attempt_id,
            readiness_generation,
        ),
        stage_name="build",
        attempt=prepared.attempt.attempt,
        attempt_id=prepared.attempt.attempt_id,
        agent_id="agent-local",
        session_id="session-1",
        offer_id="offer-failed",
        claim_id="claim-build-failed",
    )
    atom = CapacityAtom("cpu", "cpu-0", ExactQuantity(1), "count", ExactQuantity(1))
    contract = ResourceClaimContractDescriptor("cpu", 1, "cpu-contract")
    claim = ResourceClaim("cpu", contract, (atom,), 1)
    descriptor = SchedulingComponentDescriptor(
        "cpu", 1, "1", "cpu-provider", "configured"
    )
    provider = AtomResourceProvider(descriptor, (contract,), (atom,))
    coordinator_path = tmp_path / "coordinator" / "failed.sqlite"
    _seed_stage_work(
        coordinator_path,
        assignment,
        admission_id="admission-failed",
        readiness_generation=readiness_generation,
        plan_fingerprint="plan-failed",
        authority_revision=prepared.attempt.revision,
    )
    coordinator = SQLiteCoordinatorAssignments(coordinator_path, (atom,))
    coordinator.publish_offer(
        _offer_snapshot(
            assignment,
            descriptor,
            (atom,),
            availability_revision="availability-failed",
        )
    )
    journal = SQLiteAgentJournal(tmp_path / "agent" / "failed.sqlite")

    def execute():
        return run_managed_local_assignment(
            coordinator=coordinator,
            authority=authority,
            journal=journal,
            assignment=assignment,
            worker_request=worker_request,
            claims=(claim,),
            commands=(ClaimCommand(assignment, "claim-build-failed:prepare", claim),),
            providers={"cpu": provider},
            run_store=run_store,
            max_parallel_stages=1,
            decision_receipt=_decision_receipt(assignment, claim, descriptor),
            process_launcher=(
                _definitive_start_failure_launcher if failure_mode == "start" else None
            ),
        )

    receipt = execute()
    replay = execute()

    assert receipt.worker_result.status is StageStatus.FAILED
    assert replay == receipt
    assert receipt.output_commit is None
    assert authority.snapshot(run_uri).stages[0].status is StageStatus.FAILED
    assert coordinator.state(assignment.assignment_id) == "released"
    assert journal.read_state(assignment.assignment_id) is AssignmentState.RELEASED
    if failure_mode == "start":
        assert receipt.worker_result.executor_metadata["process_created"] is False
    observed = provider.observe(
        ObserveRequest("agent-local", "session-1", "observe-after-failure")
    )
    assert observed.atoms == (atom,)
    assert observed.live_claim_ids == ()


def test_definitive_decline_replays_after_unbind_response_is_lost(
    tmp_path: Path,
) -> None:
    run_store = LocalRunStore(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "declined-run")
    run_store.create_run(run_uri)
    spec = _spec()
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=run_store,
        artifact_store=LocalArtifactStore(run_store.local_artifact_root(run_uri)),
        persist=True,
    )
    worker_request = prepare_stage_attempt(
        run_store=run_store,
        run_uri=run_uri,
        stage=spec.get_stage("build"),
        stage_plan=plan.ordered_stage_plans[0],
        resolved_runtime=ResolvedStageRuntimeOptions(
            stage_id="build", executor="local"
        ),
    )
    authority = _UnbindThenTimeoutAuthority()
    revision = authority.create_run(run_uri)
    readiness_generation = "ready-build-declined"
    prepared = authority.ensure_prepared_attempt(
        run_uri,
        PreparedAttemptRequest(
            operation_id="prepare-build-declined",
            request_digest="digest-build-declined",
            admission_id="admission-declined",
            stage_name="build",
            readiness_generation=readiness_generation,
            expected_revision=revision,
            expected_stage_status=None,
            expected_attempt_id=None,
            next_attempt=1,
            owner_id="coordinator",
            plan_fingerprint="plan-declined",
            bound_inputs={},
            upstream_commits={},
        ),
    )
    assignment = ManagedAssignment(
        assignment_id="assignment-build-declined",
        run_uri=run_uri,
        stage_work_id=stage_work_identity(
            "admission-declined",
            "build",
            prepared.attempt.attempt_id,
            readiness_generation,
        ),
        stage_name="build",
        attempt=prepared.attempt.attempt,
        attempt_id=prepared.attempt.attempt_id,
        agent_id="agent-local",
        session_id="session-1",
        offer_id="offer-declined",
        claim_id="claim-build-declined",
    )
    atom = CapacityAtom("cpu", "cpu-0", ExactQuantity(1), "count", ExactQuantity(1))
    contract = ResourceClaimContractDescriptor("cpu", 1, "cpu-contract")
    claim = ResourceClaim("cpu", contract, (atom,), 1)
    descriptor = SchedulingComponentDescriptor(
        "cpu", 1, "1", "cpu-provider", "configured"
    )
    provider = AtomResourceProvider(descriptor, (contract,), ())
    coordinator_path = tmp_path / "coordinator" / "declined.sqlite"
    _seed_stage_work(
        coordinator_path,
        assignment,
        admission_id="admission-declined",
        readiness_generation=readiness_generation,
        plan_fingerprint="plan-declined",
        authority_revision=prepared.attempt.revision,
    )
    coordinator = SQLiteCoordinatorAssignments(coordinator_path, (atom,))
    coordinator.publish_offer(
        _offer_snapshot(
            assignment,
            descriptor,
            (atom,),
            availability_revision="availability-declined",
        )
    )
    journal = SQLiteAgentJournal(tmp_path / "agent" / "declined.sqlite")

    def execute():
        return run_managed_local_assignment(
            coordinator=coordinator,
            authority=authority,
            journal=journal,
            assignment=assignment,
            worker_request=worker_request,
            claims=(claim,),
            commands=(ClaimCommand(assignment, "claim-build-declined:prepare", claim),),
            providers={"cpu": provider},
            run_store=run_store,
            max_parallel_stages=1,
            decision_receipt=_decision_receipt(assignment, claim, descriptor),
        )

    with pytest.raises(TimeoutError, match="unbind response was lost"):
        execute()
    assert coordinator.state(assignment.assignment_id) == "bound"
    assert journal.read_state(assignment.assignment_id) is AssignmentState.DECLINED

    with pytest.raises(ManagedLocalError, match="definitively declined"):
        execute()
    assert coordinator.state(assignment.assignment_id) == "released"
    assert journal.read_state(assignment.assignment_id) is AssignmentState.RELEASED
    with pytest.raises(ManagedLocalError, match="definitively declined"):
        execute()
    authority.unbind_prepared_attempt(
        run_uri,
        assignment_id=assignment.assignment_id,
        attempt_id=assignment.attempt_id,
    )
    authority.bind_prepared_attempt(
        run_uri,
        assignment_id="assignment-build-replacement",
        attempt_id=assignment.attempt_id,
    )


def test_managed_independent_same_run_workers_overlap_without_run_lock(
    tmp_path: Path,
) -> None:
    marker_dir = tmp_path / "markers"
    stages = tuple(
        StageSpec(
            name=name,
            factory=StageFactorySpec(
                target_path=("tests.support.pipeline_execution_stages.CoordinatedStage")
            ),
            stage_config={
                "marker_dir": str(marker_dir),
                "wait_for": 2,
                "timeout_seconds": 20,
            },
            outputs={"data": OutputSpec(artifact_type="json", codec_key="json.v1")},
        )
        for name in ("left", "right")
    )
    spec = PipelineSpec(stages=stages)
    run_store = LocalRunStore(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "parallel")
    run_store.create_run(run_uri)
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=run_store,
        artifact_store=LocalArtifactStore(run_store.local_artifact_root(run_uri)),
        persist=True,
    )
    requests = {
        stage.name: prepare_stage_attempt(
            run_store=run_store,
            run_uri=run_uri,
            stage=stage,
            stage_plan=next(
                item
                for item in plan.ordered_stage_plans
                if item.stage_name == stage.name
            ),
            resolved_runtime=ResolvedStageRuntimeOptions(
                stage_id=stage.name, executor="local"
            ),
        )
        for stage in stages
    }

    authority = SQLitePerRunAuthorityStore()
    revision = authority.create_run(run_uri)
    prepared = {}
    for stage in stages:
        receipt = authority.ensure_prepared_attempt(
            run_uri,
            PreparedAttemptRequest(
                operation_id=f"prepare-{stage.name}",
                request_digest=f"digest-{stage.name}",
                admission_id="admission-parallel",
                stage_name=stage.name,
                readiness_generation=f"ready-{stage.name}",
                expected_revision=revision,
                expected_stage_status=None,
                expected_attempt_id=None,
                next_attempt=1,
                owner_id="coordinator",
                plan_fingerprint="plan-parallel",
                bound_inputs={},
                upstream_commits={},
            ),
        )
        prepared[stage.name] = receipt
        revision = receipt.attempt.revision

    capacity = CapacityAtom("cpu", "cpu-0", ExactQuantity(2), "count", ExactQuantity(1))
    contract = ResourceClaimContractDescriptor("cpu", 1, "cpu-contract")
    descriptor = SchedulingComponentDescriptor(
        "cpu", 1, "1", "cpu-provider", "configured"
    )
    provider = AtomResourceProvider(descriptor, (contract,), (capacity,))
    coordinator_path = tmp_path / "coordinator" / "state.sqlite"
    execution_inputs = {}
    for name in ("left", "right"):
        authority_receipt = prepared[name]
        readiness_generation = f"ready-{name}"
        assignment = ManagedAssignment(
            assignment_id=f"assignment-{name}",
            run_uri=run_uri,
            stage_work_id=stage_work_identity(
                "admission-parallel",
                name,
                authority_receipt.attempt.attempt_id,
                readiness_generation,
            ),
            stage_name=name,
            attempt=authority_receipt.attempt.attempt,
            attempt_id=authority_receipt.attempt.attempt_id,
            agent_id="agent-local",
            session_id="session-1",
            offer_id=f"offer-{name}",
            claim_id=f"claim-{name}",
        )
        claim_atom = CapacityAtom(
            "cpu", "cpu-0", ExactQuantity(1), "count", ExactQuantity(1)
        )
        claim = ResourceClaim("cpu", contract, (claim_atom,), 1)
        _seed_stage_work(
            coordinator_path,
            assignment,
            admission_id="admission-parallel",
            readiness_generation=readiness_generation,
            plan_fingerprint="plan-parallel",
            authority_revision=authority_receipt.attempt.revision,
        )
        execution_inputs[name] = (assignment, claim)

    coordinator = SQLiteCoordinatorAssignments(coordinator_path, (capacity,))
    journal = SQLiteAgentJournal(tmp_path / "agent" / "journal.sqlite")
    left_assignment, _left_claim = execution_inputs["left"]
    coordinator.publish_offer(
        _offer_snapshot(
            left_assignment,
            descriptor,
            (capacity,),
            availability_revision="availability-left",
        )
    )

    def run_one(name: str):
        assignment, claim = execution_inputs[name]
        return run_managed_local_assignment(
            coordinator=coordinator,
            authority=authority,
            journal=journal,
            assignment=assignment,
            worker_request=requests[name],
            claims=(claim,),
            commands=(ClaimCommand(assignment, f"claim-{name}:prepare", claim),),
            providers={"cpu": provider},
            run_store=run_store,
            max_parallel_stages=2,
            decision_receipt=_decision_receipt(assignment, claim, descriptor),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        left = pool.submit(run_one, "left")
        deadline = time.monotonic() + 10
        while not (marker_dir / "left.started").exists():
            if time.monotonic() >= deadline:
                raise AssertionError("left managed worker did not start")
            time.sleep(0.01)
        stage_states = {
            stage.stage_name: stage.status
            for stage in authority.snapshot(run_uri).stages
        }
        assert stage_states["left"] is StageStatus.RUNNING
        assert coordinator.state(left_assignment.assignment_id) == "running"
        assert (
            journal.read_state(left_assignment.assignment_id)
            is AssignmentState.PROCESS_STARTED
        )

        reopened_journal = SQLiteAgentJournal(journal.path)
        relaunches = 0

        def forbidden_relaunch() -> str:
            nonlocal relaunches
            relaunches += 1
            return f"{left_assignment.assignment_id}:root"

        assert (
            reopened_journal.start_once(
                left_assignment.assignment_id,
                f"{left_assignment.assignment_id}:root",
                forbidden_relaunch,
            )
            == f"{left_assignment.assignment_id}:root"
        )
        assert relaunches == 0
        assert reopened_journal.process_handle(left_assignment.assignment_id) is None
        observed = provider.observe(
            ObserveRequest("agent-local", "session-1", "observe-for-right")
        )
        right_assignment, _right_claim = execution_inputs["right"]
        coordinator.publish_offer(
            _offer_snapshot(
                right_assignment,
                descriptor,
                observed.atoms,
                availability_revision=observed.availability_revision,
                reflected_claim_ids=observed.live_claim_ids,
            )
        )
        right = pool.submit(run_one, "right")
        results = (left.result(timeout=30), right.result(timeout=30))

    assert {result.worker_result.status for result in results} == {
        StageStatus.SUCCEEDED
    }
    snapshot = authority.snapshot(run_uri)
    assert {stage.stage_name: stage.status for stage in snapshot.stages} == {
        "left": StageStatus.SUCCEEDED,
        "right": StageStatus.SUCCEEDED,
    }
