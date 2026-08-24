from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import cast

import pytest

from loom.pipeline.executors.slurm.commands import (
    FakeSlurmCommandRunner,
    SlurmCommandResult,
)
from loom.pipeline.executors.slurm.errors import (
    SlurmPlanningError,
    SlurmResourceMappingError,
)
from loom.pipeline.executors.slurm.ready_stage import (
    ReadyStageState,
    SQLiteReadyStageSubmissions,
    SlurmReadyStageProfile,
    map_ready_stage,
    operation_marker,
)
from loom.pipeline.resources import ResourceEntry, ResourceRequest
from loom.pipeline.runtime import (
    CpuResourcePlanner,
    ExecutionRoute,
    ExecutionRouteKind,
    StagePlacementPolicy,
    resolve_stage_placement,
)


def _profile(
    runner: FakeSlurmCommandRunner,
    *,
    credential_reference: str = "slurm-credential",
    available: bool = True,
    cluster: str | None = "cluster-a",
) -> SlurmReadyStageProfile:
    return SlurmReadyStageProfile(
        profile_id="training",
        partition="gpu",
        max_outstanding=1,
        bootstrap_argv=("loom", "slurm-bootstrap"),
        runner=runner,
        command_adapter_fingerprint="fake-slurm-v1",
        bootstrap_principal_id="slurm-principal",
        credential_reference=credential_reference,
        coordinator_endpoint="https://coordinator.example",
        project_fingerprint="project-v1",
        environment_fingerprint="environment-v1",
        executor_fingerprint="executor-v1",
        cluster=cluster,
        available=available,
    )


def _request(profile: SlurmReadyStageProfile):  # type: ignore[no-untyped-def]
    placement = resolve_stage_placement(
        authored=ResourceRequest(entries={"cpu": ResourceEntry("cpu", 2, "count")}),
        runtime=None,
        policy=StagePlacementPolicy(
            route=ExecutionRoute(
                kind=ExecutionRouteKind.SLURM,
                profile_id=profile.profile_id,
                profile_descriptor=profile.descriptor,
                profile_configuration_fingerprint=profile.configuration_fingerprint,
            )
        ),
        planners={"cpu": CpuResourcePlanner()},
    )
    return map_ready_stage(
        placement=placement,
        profile=profile,
        operation_id="operation-1",
        stage_work_id="work-1",
        run_uri="runs/example",
        attempt_id="attempt-1",
    )


def _script(tmp_path: Path, request) -> Path:  # type: ignore[no-untyped-def]
    path = tmp_path / "bootstrap.sh"
    path.write_text(request.script, encoding="utf-8")
    return path


def test_ready_stage_script_is_fixed_safe_and_deterministic() -> None:
    profile = _profile(FakeSlurmCommandRunner())
    request = _request(profile)

    assert request == _request(profile)
    assert f"#SBATCH --comment={operation_marker('operation-1')}" in request.script
    assert "exec 'loom' 'slurm-bootstrap'" in request.script
    assert f"--request-digest '{request.digest}'" in request.script
    assert "runs/example" not in request.script
    assert profile.credential_reference not in request.script

    with pytest.raises(SlurmPlanningError, match="fixed Loom bootstrap"):
        SlurmReadyStageProfile(
            profile_id="training",
            partition="gpu",
            max_outstanding=1,
            bootstrap_argv=("/tmp/loom", "slurm-bootstrap"),
            runner=FakeSlurmCommandRunner(),
            command_adapter_fingerprint="fake-slurm-v1",
            bootstrap_principal_id="slurm-principal",
            credential_reference="slurm-credential",
            coordinator_endpoint="https://coordinator.example",
            project_fingerprint="project-v1",
            environment_fingerprint="environment-v1",
            executor_fingerprint="executor-v1",
        )


def test_ready_stage_rejects_a_managed_pool_requirement() -> None:
    profile = _profile(FakeSlurmCommandRunner())
    placement = resolve_stage_placement(
        authored=ResourceRequest(entries={"cpu": ResourceEntry("cpu", 2, "count")}),
        runtime=None,
        policy=StagePlacementPolicy(
            pool_name="managed-gpu-pool",
            route=ExecutionRoute(
                kind=ExecutionRouteKind.SLURM,
                profile_id=profile.profile_id,
                profile_descriptor=profile.descriptor,
                profile_configuration_fingerprint=profile.configuration_fingerprint,
            ),
        ),
        planners={"cpu": CpuResourcePlanner()},
    )

    with pytest.raises(SlurmResourceMappingError, match="unmappable"):
        map_ready_stage(
            placement=placement,
            profile=profile,
            operation_id="operation-pool",
            stage_work_id="work-pool",
            run_uri="runs/example",
            attempt_id="attempt-1",
        )


def test_submission_start_permit_is_atomic_across_bootstrap_incarnations(
    tmp_path: Path,
) -> None:
    """Only one concurrent bootstrap can receive the authored-root permit."""

    profile = _profile(FakeSlurmCommandRunner())
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    accepted = store.submit(request, profile, _script(tmp_path, request))
    assert accepted.state is ReadyStageState.ACCEPTED

    with ThreadPoolExecutor(max_workers=2) as executor:
        permits = list(
            executor.map(lambda _: store.consume_start("operation-1"), range(2))
        )

    assert permits.count(True) == 1
    assert permits.count(False) == 1
    assert store.read("operation-1").start_consumed is True


def test_unknown_submit_reconciles_only_one_exact_operation(tmp_path: Path) -> None:
    marker = operation_marker("operation-1")
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "sbatch": [TimeoutError("lost response")],
            "squeue": [
                SlurmCommandResult("squeue", ("squeue",), 0, stdout=f"1200|{marker}\n")
            ],
            "sacct": [SlurmCommandResult("sacct", ("sacct",), 0)],
        }
    )
    profile = _profile(runner)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    result = store.submit(request, profile, _script(tmp_path, request))

    assert result.state is ReadyStageState.UNKNOWN
    reconciled = store.reconcile(request.operation_id, profile)
    assert reconciled.state is ReadyStageState.ACCEPTED
    assert reconciled.job_id == "1200"
    assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1
    assert store.submit(request, profile, _script(tmp_path, request)) == reconciled
    assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1


def test_zero_or_multiple_operation_matches_never_resubmit(tmp_path: Path) -> None:
    marker = operation_marker("operation-1")
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "sbatch": [TimeoutError("lost response")],
            "squeue": [
                SlurmCommandResult("squeue", ("squeue",), 0),
                SlurmCommandResult(
                    "squeue",
                    ("squeue",),
                    0,
                    stdout=f"1200|{marker}\n1201|{marker}\n",
                ),
            ],
            "sacct": [
                SlurmCommandResult("sacct", ("sacct",), 0),
                SlurmCommandResult("sacct", ("sacct",), 0),
            ],
        }
    )
    profile = _profile(runner)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    store.submit(request, profile, _script(tmp_path, request))

    assert (
        store.reconcile(request.operation_id, profile).state is ReadyStageState.UNKNOWN
    )
    conflict = store.reconcile(request.operation_id, profile)
    assert conflict.state is ReadyStageState.CONFLICT
    assert set(conflict.conflicting_handles) == {
        ("1200", "cluster-a"),
        ("1201", "cluster-a"),
    }
    assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1


def test_live_and_accounting_views_of_one_job_reconcile_as_one_handle(
    tmp_path: Path,
) -> None:
    marker = operation_marker("operation-1")
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "sbatch": [TimeoutError("lost response")],
            "squeue": [
                SlurmCommandResult("squeue", ("squeue",), 0, stdout=f"1200|{marker}\n")
            ],
            "sacct": [
                SlurmCommandResult(
                    "sacct",
                    ("sacct",),
                    0,
                    stdout=f"1200|{marker}|cluster-a|\n",
                )
            ],
        }
    )
    profile = _profile(runner, cluster=None)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    store.submit(request, profile, _script(tmp_path, request))

    reconciled = store.reconcile(request.operation_id, profile)

    assert reconciled.state is ReadyStageState.ACCEPTED
    assert reconciled.job_id == "1200"
    assert reconciled.cluster == "cluster-a"


def test_many_exact_matches_record_a_bounded_conflict(tmp_path: Path) -> None:
    marker = operation_marker("operation-1")
    rows = "".join(f"{job_id}|{marker}\n" for job_id in range(1200, 1220))
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "sbatch": [TimeoutError("lost response")],
            "squeue": [SlurmCommandResult("squeue", ("squeue",), 0, stdout=rows)],
            "sacct": [SlurmCommandResult("sacct", ("sacct",), 0)],
        }
    )
    profile = _profile(runner)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    store.submit(request, profile, _script(tmp_path, request))

    conflict = store.reconcile(request.operation_id, profile)

    assert conflict.state is ReadyStageState.CONFLICT
    assert len(conflict.conflicting_handles) == 16


def test_bootstrap_handle_repairs_response_race_and_conflict_is_closed(
    tmp_path: Path,
) -> None:
    runner = FakeSlurmCommandRunner(
        scripted_results={"sbatch": [TimeoutError("lost response")]}
    )
    profile = _profile(runner)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    store.submit(request, profile, _script(tmp_path, request))

    accepted = store.associate_handle(
        request.operation_id, profile, job_id="1200", cluster="cluster-a"
    )
    assert accepted.state is ReadyStageState.ACCEPTED
    assert (
        store.associate_handle(
            request.operation_id, profile, job_id="1200", cluster="cluster-a"
        )
        == accepted
    )
    conflict = store.associate_handle(
        request.operation_id, profile, job_id="1201", cluster="cluster-a"
    )
    assert conflict.state is ReadyStageState.CONFLICT
    assert set(conflict.conflicting_handles) == {
        ("1200", "cluster-a"),
        ("1201", "cluster-a"),
    }


def test_bootstrap_handle_wins_a_late_unknown_submit_response(tmp_path: Path) -> None:
    entered = Event()
    release = Event()

    class BlockingRunner(FakeSlurmCommandRunner):
        def sbatch(self, script_path, *, dependency_job_ids=(), comment=None):  # type: ignore[no-untyped-def]
            del script_path, dependency_job_ids, comment
            entered.set()
            assert release.wait(timeout=5)
            return SlurmCommandResult(
                "sbatch", ("sbatch",), 0, stdout="unusable-success"
            )

    runner = BlockingRunner()
    profile = _profile(runner)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    script = _script(tmp_path, request)

    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = executor.submit(store.submit, request, profile, script)
        assert entered.wait(timeout=5)
        associated = store.associate_handle(
            request.operation_id,
            profile,
            job_id="1200",
            cluster="cluster-a",
        )
        release.set()
        completed = pending.result(timeout=5)

    assert associated.state is ReadyStageState.ACCEPTED
    assert completed == associated
    assert store.read(request.operation_id) == associated


def test_two_concurrent_bootstrap_handles_close_as_conflict(tmp_path: Path) -> None:
    runner = FakeSlurmCommandRunner(
        scripted_results={"sbatch": [TimeoutError("lost response")]}
    )
    profile = _profile(runner)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    store.submit(request, profile, _script(tmp_path, request))

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            executor.map(
                lambda job_id: store.associate_handle(
                    request.operation_id,
                    profile,
                    job_id=job_id,
                    cluster="cluster-a",
                ),
                ("1200", "1201"),
            )
        )

    assert ReadyStageState.CONFLICT in {result.state for result in results}
    conflict = store.read(request.operation_id)
    assert conflict.state is ReadyStageState.CONFLICT
    assert set(conflict.conflicting_handles) == {
        ("1200", "cluster-a"),
        ("1201", "cluster-a"),
    }


def test_changed_profile_and_script_bytes_are_rejected_before_sbatch(
    tmp_path: Path,
) -> None:
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner)
    request = _request(profile)
    changed = _profile(runner, credential_reference="changed-credential")
    path = _script(tmp_path, request)

    with pytest.raises(SlurmPlanningError, match="profile identity"):
        SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite").submit(
            request, changed, path
        )
    path.write_text(request.script + "# changed\n", encoding="utf-8")
    with pytest.raises(SlurmPlanningError, match="script bytes"):
        SQLiteReadyStageSubmissions(tmp_path / "submissions-2.sqlite").submit(
            request, profile, path
        )
    assert not [call for call in runner.calls if call[0] == "sbatch"]


def test_unavailable_profile_rejects_the_exact_route_without_sbatch() -> None:
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner, available=False)

    with pytest.raises(SlurmPlanningError, match="slurm_profile_unavailable"):
        _request(profile)

    assert not [call for call in runner.calls if call[0] == "sbatch"]


def test_exact_cancel_records_only_a_request_and_keeps_assignment_nonterminal(
    tmp_path: Path,
) -> None:
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    accepted = store.submit(request, profile, _script(tmp_path, request))

    cancelled = store.request_cancel(request.operation_id, profile)
    assert accepted.state is ReadyStageState.ACCEPTED
    assert cancelled.state is ReadyStageState.ACCEPTED
    assert cancelled.cancel_requested is True
    assert cancelled.job_id == accepted.job_id
    assert [call for call in runner.calls if call[0] == "scancel"] == [
        ("scancel", ("scancel", cast(str, accepted.job_id)))
    ]


def test_scheduler_completed_is_observation_not_loom_terminality(
    tmp_path: Path,
) -> None:
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "squeue": [
                SlurmCommandResult(
                    "squeue",
                    ("squeue",),
                    0,
                    stdout="1000|COMPLETED|None\n",
                )
            ]
        }
    )
    profile = _profile(runner)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    accepted = store.submit(request, profile, _script(tmp_path, request))

    observed = store.observe(request.operation_id, profile)

    assert accepted.state is ReadyStageState.ACCEPTED
    assert observed.state is ReadyStageState.ACCEPTED
    assert observed.scheduler_state == "COMPLETED"
    assert observed.scheduler_source == "squeue"
    assert observed.scheduler_observed_at is not None
    assert observed.start_consumed is False


def test_rejected_scancel_does_not_claim_cancellation_was_requested(
    tmp_path: Path,
) -> None:
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "scancel": [SlurmCommandResult("scancel", ("scancel", "1000"), 1)]
        }
    )
    profile = _profile(runner)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    store.submit(request, profile, _script(tmp_path, request))

    result = store.request_cancel(request.operation_id, profile)

    assert result.state is ReadyStageState.ACCEPTED
    assert result.cancel_requested is False
    assert result.evidence == "slurm_cancel_request_rejected"
