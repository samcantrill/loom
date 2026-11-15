"""Quantity admission uses real independent SQLite transactions and retained rows."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields, replace
from threading import Barrier

import pytest

from loom._sqlite_policy import SQLitePolicy
from loom.pipeline.executors.slurm.commands import FakeSlurmCommandRunner
from loom.pipeline.executors.slurm.ready_stage import map_ready_stage
from loom.pipeline.orchestration import (
    ExecutionRequirement, SQLiteStageWorkStore, StageWorkRecord, stage_work_identity,
)
from loom.pipeline.resources import ResourceEntry, ResourceRequest
from loom.pipeline.runtime import (
    CpuResourcePlanner, ExecutionRoute, ExecutionRouteKind,
    StagePlacementPolicy, resolve_stage_placement,
)
from loom.pipeline.runtime.scheduling_resources import GpuResourcePlanner
from loom.pipeline.stores import BackendRevision
from loom.queue._managed_local import SQLiteCoordinatorAssignments
from loom.queue._slurm_admission import SlurmAdmissionDeferred
from loom.queue.slurm_ready_stage import (
    SQLiteSlurmStageAssignments, SlurmStageAssignment, SlurmStageDelivery,
)
from loom.queue.errors import QueueConflictError
from tests.unit.loom.pipeline.executors.slurm.test_ready_stage import _profile
from tests.unit.loom.queue.test_remote_stage_execution import (
    _profile as _resident_profile, _request as _resident_request,
)


class ReservationFixture:
    def __init__(self, root, *, schema_version=4):
        self.schema_version = schema_version
        self.path = root / "execution.sqlite"
        self.transfers = root / "transfers"
        self.policy = SQLitePolicy("delete", "extra")
        self.work = SQLiteStageWorkStore(self.path, sqlite_policy=self.policy)
        self.work._initialize()
        SQLiteCoordinatorAssignments(self.path, (), sqlite_policy=self.policy)._initialize()
        self.store = SQLiteSlurmStageAssignments(
            self.path, self.transfers, sqlite_policy=self.policy, schema_version=schema_version,
        )
        self.store._initialize()
        self.bundle = _resident_request(_resident_profile(root))
        self.profile = replace(
            _profile(FakeSlurmCommandRunner()), max_outstanding=None,
            project_fingerprint="project-1", environment_fingerprint="env-1",
            executor_fingerprint="executor-1",
        )
        self.input = root / "input"
        self.input.write_bytes(b"input")

    def reopen(self):
        return SQLiteSlurmStageAssignments(
            self.path, self.transfers, sqlite_policy=self.policy,
            schema_version=self.schema_version, _allow_initialize=False,
        )

    def candidate(self, key, quantity, *, profile_id="training", run_uri=None):
        profile = replace(self.profile, profile_id=profile_id)
        resources = ResourceRequest(entries={
            "cpu": ResourceEntry("cpu", 2, "count"),
            **({"gpu": ResourceEntry("gpu", quantity, "count", {"allocation_mode": "exclusive"})}
               if quantity else {}),
        })
        placement = resolve_stage_placement(
            authored=resources, runtime=None,
            policy=StagePlacementPolicy(route=ExecutionRoute(
                kind=ExecutionRouteKind.SLURM, profile_id=profile.profile_id,
                profile_descriptor=profile.descriptor,
                profile_configuration_fingerprint=profile.configuration_fingerprint,
            )),
            planners={"cpu": CpuResourcePlanner(), "gpu": GpuResourcePlanner()},
        )
        work_id = stage_work_identity(key, "build", key, "ready")
        request = map_ready_stage(
            placement=placement, profile=profile, operation_id=key,
            stage_work_id=work_id, run_uri=run_uri or f"file:///run-{key}",
            attempt_id=key, _check_commands=False,
        )
        assignment = SlurmStageAssignment(
            assignment_id=key, operation_id=key, run_uri=request.run_uri,
            stage_work_id=work_id, stage_name="build", attempt=1, attempt_id=key,
            profile_id=profile.profile_id, profile_descriptor=profile.descriptor,
            profile_configuration_fingerprint=profile.configuration_fingerprint,
            request_digest=request.digest, agent_id="submit", agent_root_id="submit-root",
        )
        self.work.create_or_refresh(StageWorkRecord(
            stage_work_id=work_id, admission_id=key, run_uri=request.run_uri,
            stage_name="build", attempt=1, attempt_id=key,
            readiness_generation="ready", ready_at=0, ready_order=0,
            plan_fingerprint="plan", authority_revision=BackendRevision(1, "revision"),
            bound_inputs={}, upstream_commits={}, placement=placement,
            execution_requirement=ExecutionRequirement("project-1", "env-1", "executor-1"),
        ))
        values = {
            field.name: getattr(self.bundle, field.name)
            for field in fields(SlurmStageDelivery)
            if hasattr(self.bundle, field.name) and field.name != "schema_version"
        }
        values.update(
            assignment_id=key, stage_work_id=work_id, attempt_id=key,
            profile_id=profile.profile_id, project_fingerprint="project-1",
            environment_fingerprint="env-1", executor_fingerprint="executor-1",
        )
        delivery = SlurmStageDelivery(**values)
        return assignment, dict(
            request_json=request.to_dict(), delivery=delivery,
            input_paths={"input-1": self.input}, issuer_epoch="epoch",
            max_parallel_stages=100, max_profile_outstanding=None,
            requested_gpu_count=quantity, max_reserved_gpus=8,
        )


@pytest.mark.parametrize("quantities", [(1,) * 8, (2,) * 4, (3, 2, 3)])
def test_gpu_quantity_is_shared_across_profiles_and_cpu_stays_admissible(tmp_path, quantities):
    fixture = ReservationFixture(tmp_path)
    for index, quantity in enumerate(quantities):
        assignment, arguments = fixture.candidate(str(index), quantity, profile_id=f"profile-{index % 2}")
        assert fixture.store.reserve(assignment, **arguments) == "reserved"
        assert fixture.store.reserve(assignment, **arguments) == "reserved"
    reopened = fixture.reopen()
    assert reopened.reserved_gpu_count() == 8
    assignment, arguments = fixture.candidate("ninth", 1)
    with pytest.raises(SlurmAdmissionDeferred) as error:
        reopened.reserve(assignment, **arguments)
    assert error.value.code == "slurm_gpu_capacity_reserved"
    cpu, cpu_arguments = fixture.candidate("cpu", 0)
    assert reopened.reserve(cpu, **cpu_arguments) == "reserved"
    assert reopened.reserved_gpu_count() == 8
    with pytest.raises(QueueConflictError, match="replay"):
        reopened.reserve(cpu, **{**cpu_arguments, "requested_gpu_count": 1})
    assert reopened.reserved_gpu_count() == 8


def test_last_gpu_race_has_one_winner_across_independent_connections(tmp_path):
    fixture = ReservationFixture(tmp_path)
    first, arguments = fixture.candidate("first", 7)
    fixture.store.reserve(first, **arguments)
    candidates = [fixture.candidate(key, 1) for key in ("left", "right")]
    barrier = Barrier(2)

    def reserve(candidate):
        store = fixture.reopen()
        barrier.wait(timeout=5)
        try:
            store.reserve(candidate[0], **candidate[1])
            return "reserved"
        except SlurmAdmissionDeferred as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, candidates))
    assert sorted(results) == ["reserved", "slurm_gpu_capacity_reserved"]
    assert fixture.reopen().reserved_gpu_count() == 8


@pytest.mark.parametrize("uncertain", [False, True])
def test_every_unreleased_state_holds_quantity_until_release(tmp_path, uncertain):
    fixture = ReservationFixture(tmp_path)
    assignment, arguments = fixture.candidate("existing", 8)
    fixture.store.reserve(assignment, **arguments)
    states = ["reserved", "bound", "submitting"]
    if uncertain:
        states.append("unknown")
    states.extend(["accepted", "granted", "running", "terminal", "logical_released"])
    for before, after in zip(states, states[1:]):
        fixture.store.advance(assignment.assignment_id, expected=before, next_state=after)
        assert fixture.reopen().reserved_gpu_count() == 8
    next_assignment, next_arguments = fixture.candidate("next", 1)
    with pytest.raises(SlurmAdmissionDeferred):
        fixture.store.reserve(next_assignment, **next_arguments)
    fixture.store.release(assignment.assignment_id)
    fixture.store.release(assignment.assignment_id)
    assert fixture.reopen().reserved_gpu_count() == 0
    fixture.store.reserve(next_assignment, **next_arguments)
    assert fixture.reopen().reserved_gpu_count() == 1


def test_oversized_and_mismatched_request_do_not_reserve(tmp_path):
    fixture = ReservationFixture(tmp_path)
    assignment, arguments = fixture.candidate("oversized", 9)
    with pytest.raises(SlurmAdmissionDeferred) as error:
        fixture.store.reserve(assignment, **arguments)
    assert error.value.code == "slurm_gpu_request_exceeds_budget"
    with pytest.raises(QueueConflictError, match="quantity conflicts"):
        fixture.store.reserve(assignment, **{**arguments, "requested_gpu_count": 0})
    assert fixture.store.reserved_gpu_count() == 0
    # Explicitly disabling the ceiling keeps quantity-bearing schema 4.
    fixture.store.reserve(assignment, **{**arguments, "max_reserved_gpus": None})
    assert fixture.reopen().reserved_gpu_count() == 9


def test_profile_and_run_limits_have_separate_diagnostics(tmp_path):
    fixture = ReservationFixture(tmp_path)
    first, arguments = fixture.candidate("one", 1, run_uri="file:///same-run")
    fixture.store.reserve(first, **arguments)
    second, arguments = fixture.candidate("two", 1, run_uri="file:///same-run")
    with pytest.raises(SlurmAdmissionDeferred) as error:
        fixture.store.reserve(second, **{**arguments, "max_profile_outstanding": 1})
    assert error.value.code == "slurm_profile_outstanding_limit"
    with pytest.raises(SlurmAdmissionDeferred) as error:
        fixture.store.reserve(second, **{**arguments, "max_parallel_stages": 1})
    assert error.value.code == "run_active_assignment_limit"
    assert fixture.store.reserved_gpu_count() == 1


def test_unlimited_run_still_enforces_shared_gpu_budget_after_restart(tmp_path):
    fixture = ReservationFixture(tmp_path)
    run_uri = "file:///unlimited-run"
    for index in range(10):
        assignment, arguments = fixture.candidate(str(index), 1 if index < 8 else 0, run_uri=run_uri)
        arguments["max_parallel_stages"] = None
        assert fixture.store.reserve(assignment, **arguments) == "reserved"
    assignment, arguments = fixture.candidate("ninth-gpu", 1, run_uri=run_uri)
    arguments["max_parallel_stages"] = None
    with pytest.raises(SlurmAdmissionDeferred, match="GPU"):
        fixture.reopen().reserve(assignment, **arguments)


def test_agent_task_page_filters_owner_before_limit_and_survives_restart(tmp_path):
    fixture = ReservationFixture(tmp_path)
    from dataclasses import replace
    for index in range(6):
        assignment, arguments = fixture.candidate(f"task-{index}", 0)
        assignment = replace(assignment, agent_id="other" if index % 2 else "selected")
        fixture.store.reserve(assignment, **arguments)
    selected_root = assignment.agent_root_id
    first = fixture.store.agent_page("selected", selected_root, limit=2)
    assert [row.assignment.assignment_id for row in first] == ["task-0", "task-2"]
    remaining = fixture.store.agent_page("selected", selected_root, after="task-2", limit=2)
    assert [row.assignment.assignment_id for row in remaining] == ["task-4"]
    assert fixture.store.agent_page("selected", "wrong-root") == ()
    assert fixture.reopen().agent_page("selected", selected_root, after="task-2", limit=2) == remaining


def test_compute_release_preserves_assignment_and_storage_ownership(tmp_path):
    from loom.queue.errors import QueueConflictError

    fixture = ReservationFixture(tmp_path, schema_version=5)
    assignment, arguments = fixture.candidate("retaining", 2)
    fixture.store.reserve(assignment, **arguments)
    evidence = {"provider_released": True, "release": {"kind": "definite_rejection"}}
    fixture.store.accept_agent_evidence(assignment.assignment_id, 1, evidence)
    with pytest.raises(QueueConflictError):
        fixture.store.release_compute(assignment.assignment_id, 1, evidence)
    fixture.store.advance(assignment.assignment_id, expected="reserved", next_state="bound")
    fixture.store.advance(assignment.assignment_id, expected="bound", next_state="submitting")
    fixture.store.advance(assignment.assignment_id, expected="submitting", next_state="rejected")
    fixture.store.advance(assignment.assignment_id, expected="rejected", next_state="logical_released")
    fixture.store.release_compute(assignment.assignment_id, 1, evidence)
    reopened = fixture.reopen()
    assert reopened.reserved_gpu_count() == 0
    record = reopened.read(assignment.assignment_id)
    assert record.state == "logical_released"
    assert record.compute_released_at is not None
    assert reopened.agent_evidence(assignment.assignment_id) == (1, evidence)
    reopened.release_compute(assignment.assignment_id, 1, evidence)
    assert reopened.read(assignment.assignment_id).compute_released_at == record.compute_released_at
    with pytest.raises(QueueConflictError):
        reopened.release_compute(assignment.assignment_id, 2, evidence)
