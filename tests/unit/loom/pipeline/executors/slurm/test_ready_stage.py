from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
from pathlib import Path
import sqlite3
import sys
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
    SlurmJobPrivateFileProvider,
    SlurmReadyStageProfile,
    SlurmReadyStageSubmission,
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

_TEST_HELPER = (
    sys.executable,
    str(Path(__file__).parents[5] / "support" / "slurm_job_private_helper.py"),
)


def _profile(
    runner: FakeSlurmCommandRunner,
    *,
    credential_reference: str = "slurm-credential",
    available: bool = True,
    cluster: str | None = "cluster-a",
    provider: SlurmJobPrivateFileProvider | None = None,
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
        job_private_file_provider=provider
        or SlurmJobPrivateFileProvider(
            fixed_path="/tmp/loom-unit-capability",
            descriptor="fake-prolog-v1",
            helper_argv=_TEST_HELPER,
        ),
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
    assert "capability" not in request.script

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
            job_private_file_provider=SlurmJobPrivateFileProvider(
                fixed_path="/tmp/loom-unit-capability",
                descriptor="fake-prolog-v1",
                helper_argv=_TEST_HELPER,
            ),
        )


def test_job_private_provider_requires_a_concrete_site_helper() -> None:
    with pytest.raises(SlurmPlanningError, match="helper"):
        SlurmJobPrivateFileProvider(
            fixed_path="/tmp/capability", descriptor="site-helper", helper_argv=()
        )


def test_job_private_helper_is_verifier_only_and_replays_across_fresh_provider() -> (
    None
):
    first = SlurmJobPrivateFileProvider(
        fixed_path="/tmp/loom-unit-capability-replay",
        descriptor="fake-prolog-v1",
        helper_argv=_TEST_HELPER,
    )
    prepared = first.prepare(operation_id="operation-1", request_digest="digest-1")
    second = SlurmJobPrivateFileProvider(
        fixed_path="/tmp/loom-unit-capability-replay",
        descriptor="fake-prolog-v1",
        helper_argv=_TEST_HELPER,
    )

    assert (
        second.prepare(operation_id="operation-1", request_digest="digest-1")
        == prepared
    )
    assert not hasattr(first, "test_secret")
    assert not hasattr(first, "_prepared")
    material = Path(first.fixed_path).read_bytes()
    assert hashlib.sha256(material).hexdigest() == prepared.verifier
    assert material.hex() not in repr(prepared)


def test_indeterminate_or_conflicting_helper_result_never_reaches_sbatch(
    tmp_path: Path,
) -> None:
    unavailable = SlurmJobPrivateFileProvider(
        fixed_path=str(tmp_path / "capability"),
        descriptor="fake-prolog-v1",
        helper_argv=("/bin/false",),
    )
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner, provider=unavailable)
    request = _request(profile)

    with pytest.raises(SlurmPlanningError, match="helper"):
        SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite").submit(
            request, profile, _script(tmp_path, request)
        )
    assert not [call for call in runner.calls if call[0] == "sbatch"]

    conflicting = SlurmJobPrivateFileProvider(
        fixed_path=str(tmp_path / "capability"),
        descriptor="fake-prolog-v1",
        helper_argv=(sys.executable, "-c", "print('{}')"),
    )
    conflict_runner = FakeSlurmCommandRunner()
    conflict_profile = _profile(conflict_runner, provider=conflicting)
    conflict_request = _request(conflict_profile)
    with pytest.raises(SlurmPlanningError, match="helper"):
        SQLiteReadyStageSubmissions(tmp_path / "conflict.sqlite").submit(
            conflict_request, conflict_profile, _script(tmp_path, conflict_request)
        )
    assert not [call for call in conflict_runner.calls if call[0] == "sbatch"]


def test_definite_submit_rejection_retains_site_material_for_release_owner(
    tmp_path: Path,
) -> None:
    path = tmp_path / "capability"
    provider = SlurmJobPrivateFileProvider(
        fixed_path=str(path), descriptor="fake-prolog-v1", helper_argv=_TEST_HELPER
    )
    runner = FakeSlurmCommandRunner(
        scripted_results={"sbatch": [SlurmCommandResult("sbatch", ("sbatch",), 1)]}
    )
    profile = _profile(runner, provider=provider)
    request = _request(profile)

    result = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite").submit(
        request, profile, _script(tmp_path, request)
    )
    assert result.state is ReadyStageState.REJECTED
    assert path.exists()


def test_ready_stage_submit_uses_explicit_environment_and_export_nil(
    tmp_path: Path,
) -> None:
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")

    store.submit(request, profile, _script(tmp_path, request))

    sbatch_call = next(call for call in runner.calls if call[0] == "sbatch")
    assert "--export=NIL" in sbatch_call[1]
    assert runner.environments == [{}]


def test_ready_stage_publishes_the_submit_barrier_before_runner(
    tmp_path: Path,
) -> None:
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    barriers: list[SlurmReadyStageSubmission] = []

    def assert_barrier(value: SlurmReadyStageSubmission) -> None:
        assert not runner.calls
        barriers.append(value)

    result = store.submit(
        request,
        profile,
        _script(tmp_path, request),
        before_runner=assert_barrier,
    )

    assert result.state is ReadyStageState.ACCEPTED
    assert len(barriers) == 1
    assert barriers[0].state is ReadyStageState.SUBMITTING
    assert barriers[0].capability is not None
    assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1


def test_ready_stage_can_suppress_sbatch_at_the_final_submit_barrier(
    tmp_path: Path,
) -> None:
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")

    result = store.submit(
        request,
        profile,
        _script(tmp_path, request),
        before_runner=lambda submitting: False,
    )

    assert result.state is ReadyStageState.REJECTED
    assert result.evidence == "slurm_submit_suppressed_before_call"
    assert not [call for call in runner.calls if call[0] == "sbatch"]
    assert store.read(request.operation_id) == result


def test_ready_stage_hard_cut_rejects_prior_wire_and_store_versions(
    tmp_path: Path,
) -> None:
    profile = _profile(FakeSlurmCommandRunner())
    request = _request(profile)
    for version in (1, 2):
        with pytest.raises(SlurmPlanningError, match="schema"):
            type(request).from_dict({**request.to_dict(), "schema_version": version})

    path = tmp_path / "submissions.sqlite"
    SQLiteReadyStageSubmissions(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        conn.execute("PRAGMA user_version = 2")
    with pytest.raises(SlurmPlanningError, match="store is unsupported"):
        SQLiteReadyStageSubmissions(path, _allow_initialize=False)._open_existing()


def test_fresh_submission_store_never_reprepares_or_resubmits_after_submitting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner)
    request = _request(profile)
    path = tmp_path / "submissions.sqlite"
    first = SQLiteReadyStageSubmissions(path)
    original_compare_and_set = SQLiteReadyStageSubmissions._compare_and_set

    def crash_after_submitting(
        owner: SQLiteReadyStageSubmissions,
        operation_id: str,
        *,
        expected: ReadyStageState,
        value: SlurmReadyStageSubmission,
    ) -> SlurmReadyStageSubmission:
        result = original_compare_and_set(
            owner, operation_id, expected=expected, value=value
        )
        if value.state is ReadyStageState.SUBMITTING:
            raise OSError("crash after durable submitting")
        return result

    monkeypatch.setattr(
        SQLiteReadyStageSubmissions, "_compare_and_set", crash_after_submitting
    )
    with pytest.raises(OSError, match="durable submitting"):
        first.submit(request, profile, _script(tmp_path, request))

    class FailingProvider(SlurmJobPrivateFileProvider):
        def prepare(self, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("must not prepare")

    reopened_profile = replace(
        profile,
        job_private_file_provider=FailingProvider(
            fixed_path="/tmp/loom-unit-capability",
            descriptor="fake-prolog-v1",
            helper_argv=_TEST_HELPER,
        ),
    )
    reopened = SQLiteReadyStageSubmissions(path, _allow_initialize=False)
    sentinel_runner = FakeSlurmCommandRunner(
        scripted_results={"sbatch": [AssertionError("must not submit")]}
    )
    reopened_profile = replace(reopened_profile, runner=sentinel_runner)
    assert (
        reopened.submit(request, reopened_profile, _script(tmp_path, request)).state
        is ReadyStageState.SUBMITTING
    )
    assert not [call for call in sentinel_runner.calls if call[0] == "sbatch"]


def test_fresh_store_submits_retained_prepared_receipt_without_reprepare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_runner = FakeSlurmCommandRunner()
    profile = _profile(first_runner)
    request = _request(profile)
    path = tmp_path / "prepared.sqlite"
    original_compare_and_set = SQLiteReadyStageSubmissions._compare_and_set

    def crash_after_prepared(
        owner: SQLiteReadyStageSubmissions,
        operation_id: str,
        *,
        expected: ReadyStageState,
        value: SlurmReadyStageSubmission,
    ) -> SlurmReadyStageSubmission:
        result = original_compare_and_set(
            owner, operation_id, expected=expected, value=value
        )
        if value.capability is not None and value.state is ReadyStageState.INTENT:
            raise OSError("crash after durable prepared receipt")
        return result

    monkeypatch.setattr(
        SQLiteReadyStageSubmissions, "_compare_and_set", crash_after_prepared
    )
    with pytest.raises(OSError, match="durable prepared receipt"):
        SQLiteReadyStageSubmissions(path).submit(
            request, profile, _script(tmp_path, request)
        )

    class FailingProvider(SlurmJobPrivateFileProvider):
        def prepare(self, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("must not prepare")

    fresh_runner = FakeSlurmCommandRunner()
    reopened_profile = replace(
        profile,
        runner=fresh_runner,
        job_private_file_provider=FailingProvider(
            fixed_path="/tmp/loom-unit-capability",
            descriptor="fake-prolog-v1",
            helper_argv=_TEST_HELPER,
        ),
    )
    result = SQLiteReadyStageSubmissions(path, _allow_initialize=False).submit(
        request, reopened_profile, _script(tmp_path, request)
    )
    assert result.state is ReadyStageState.ACCEPTED
    assert len([call for call in fresh_runner.calls if call[0] == "sbatch"]) == 1


def test_fresh_accepted_store_uses_neither_provider_nor_sbatch(tmp_path: Path) -> None:
    first_runner = FakeSlurmCommandRunner()
    profile = _profile(first_runner)
    request = _request(profile)
    path = tmp_path / "accepted.sqlite"
    assert (
        SQLiteReadyStageSubmissions(path)
        .submit(request, profile, _script(tmp_path, request))
        .state
        is ReadyStageState.ACCEPTED
    )

    class FailingProvider(SlurmJobPrivateFileProvider):
        def prepare(self, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("must not prepare")

    fresh_runner = FakeSlurmCommandRunner(
        scripted_results={"sbatch": [AssertionError("must not submit")]}
    )
    reopened_profile = replace(
        profile,
        runner=fresh_runner,
        job_private_file_provider=FailingProvider(
            fixed_path="/tmp/loom-unit-capability",
            descriptor="fake-prolog-v1",
            helper_argv=_TEST_HELPER,
        ),
    )
    assert (
        SQLiteReadyStageSubmissions(path, _allow_initialize=False)
        .submit(request, reopened_profile, _script(tmp_path, request))
        .state
        is ReadyStageState.ACCEPTED
    )
    assert not fresh_runner.calls


def test_fresh_unknown_store_reconciles_without_reprepare_or_resubmit(
    tmp_path: Path,
) -> None:
    first_runner = FakeSlurmCommandRunner(scripted_results={"sbatch": [TimeoutError()]})
    profile = _profile(first_runner)
    request = _request(profile)
    path = tmp_path / "unknown.sqlite"
    assert (
        SQLiteReadyStageSubmissions(path)
        .submit(request, profile, _script(tmp_path, request))
        .state
        is ReadyStageState.UNKNOWN
    )

    class FailingProvider(SlurmJobPrivateFileProvider):
        def prepare(self, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("must not prepare")

    marker = operation_marker(request.operation_id)
    fresh_runner = FakeSlurmCommandRunner(
        scripted_results={
            "sbatch": [AssertionError("must not submit")],
            "squeue": [
                SlurmCommandResult("squeue", ("squeue",), 0, stdout=f"1200|{marker}\n")
            ],
            "sacct": [SlurmCommandResult("sacct", ("sacct",), 0)],
        }
    )
    reopened_profile = replace(
        profile,
        runner=fresh_runner,
        job_private_file_provider=FailingProvider(
            fixed_path="/tmp/loom-unit-capability",
            descriptor="fake-prolog-v1",
            helper_argv=_TEST_HELPER,
        ),
    )
    result = SQLiteReadyStageSubmissions(path, _allow_initialize=False).reconcile(
        request.operation_id, reopened_profile
    )
    assert result.state is ReadyStageState.ACCEPTED
    assert result.job_id == "1200"
    assert not [call for call in fresh_runner.calls if call[0] == "sbatch"]


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
        def sbatch(
            self, script_path, *, dependency_job_ids=(), comment=None, environment=None
        ):  # type: ignore[no-untyped-def]
            del script_path, dependency_job_ids, comment, environment
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
