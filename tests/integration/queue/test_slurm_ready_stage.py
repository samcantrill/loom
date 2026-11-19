"""Explicit ready-stage SLURM production-path integration coverage."""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import base64
import json
import sqlite3
import subprocess
import shutil
import sys
import time
from threading import Event
from typing import cast

import pytest

import loom.queue.slurm_ready_stage as slurm_ready_stage
from loom.pipeline import PipelineSpec, ProcessContainmentOwner
from loom.pipeline.execution.stage_worker import execute_resident_stage_worker_request
from loom.pipeline.executors.slurm.commands import (
    FakeSlurmCommandRunner,
    SlurmCommandPolicy,
    SlurmCommandResult,
)
from loom.pipeline.executors.slurm.ready_stage import (
    SQLiteReadyStageSubmissions,
    SlurmPlanningError,
    SlurmJobPrivateFileProvider,
    SlurmContainmentHelper,
    SlurmReadyStageProfile,
    resolve_slurm_containment,
)
from loom.pipeline.planning import plan_pipeline
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore, path_to_run_uri
from loom.pipeline.stores.sqlite_authority import (
    SQLitePerRunAuthorityStore,
    _authority_database_path,
)
from loom.queue import (
    LocalDaemon,
    ExecutionRequirement,
    LocalDaemonAdmissionRequest,
    LocalDaemonAdmissionState,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    RecoverUnknownAssignment,
    ResidentWorkerLaunchProfile,
    SlurmRecoveryTarget,
    TimeRecoveryRequest,
    prepare_managed_local_runtime_record,
)
from loom.queue.agent_sessions import AgentPolicyConfig, TransportPrincipalPolicy
from loom.queue.agent_session_transport import _dispatch_application
from loom.queue.errors import QueueConflictError, QueueServiceError
from loom.queue._remote_stage_execution import ResidentProfileDescriptor
from loom.queue.slurm_ready_stage import SlurmBootstrapWorkspace, SlurmStageDelivery
from loom.serialization import PlainData, json_dumps_pretty


pytestmark = pytest.mark.integration
_RESULT_ROOT = Path("/unconfigured-test-root")


@pytest.fixture(autouse=True)
def _result_root(tmp_path, monkeypatch):
    root = tmp_path / "shared-results"
    root.mkdir()
    monkeypatch.setattr(sys.modules[__name__], "_RESULT_ROOT", root)


def _execution_requirements(pipeline: PipelineSpec) -> dict[str, ExecutionRequirement]:
    return {
        stage_name: ExecutionRequirement(
            "test-project", "test-environment", "test-executor"
        )
        for stage_name in pipeline.stage_names
    }


_TEST_HELPER = (
    sys.executable,
    str(Path(__file__).parents[2] / "support" / "slurm_job_private_helper.py"),
)


def _launch_profile() -> ResidentWorkerLaunchProfile:
    return ResidentWorkerLaunchProfile(
        Path.cwd(),
        Path(sys.executable),
        ResidentProfileDescriptor(
            "test-local", "v1", "test-project", "test-environment", "test-executor"
        ).to_dict(),
    )


def _profile(
    runner: FakeSlurmCommandRunner,
    *,
    max_outstanding: int | None = 1,
    available: bool = True,
    containment_helper: SlurmContainmentHelper | None = None,
    capability_path: Path | None = None,
    container_options: Mapping[str, object] | None = None,
) -> SlurmReadyStageProfile:
    result_root = (
        _RESULT_ROOT
        if capability_path is None
        else capability_path.parent / "shared-results"
    )
    result_root.mkdir(parents=True, exist_ok=True)
    return SlurmReadyStageProfile(
        result_storage={
            "agent_root": str(result_root),
            "compute_root": str(result_root),
            "retention_bytes": 1024 * 1024 * 1024,
        },
        profile_id="training",
        partition="gpu",
        max_outstanding=max_outstanding,
        bootstrap_argv=("loom", "slurm-bootstrap"),
        runner=runner,
        command_adapter_fingerprint="fake-slurm-v1",
        bootstrap_principal_id="slurm-principal",
        credential_reference="slurm-credential",
        coordinator_endpoint="https://coordinator.example",
        project_fingerprint="project-v1",
        environment_fingerprint="environment-v1",
        executor_fingerprint="executor-v1",
        job_private_file_provider=SlurmJobPrivateFileProvider(
            fixed_path=str(capability_path or _RESULT_ROOT.parent / "capability"),
            descriptor="fake-prolog-v1",
            helper_argv=_TEST_HELPER,
        ),
        cluster="cluster-a",
        available=available,
        containment_helper=containment_helper,
        container_options=container_options,
    )


def _positive_containment_helper(*, accounting_identity: bool = False) -> SlurmContainmentHelper:
    identity_check = (
        "assert value['accounting_identity']['db_index'] == '1200'; "
        "assert value['accounting_identity']['sluid'] == 'sFixture1200'; "
    ) if accounting_identity else ""
    program = (
        "import json,sys; value=json.load(sys.stdin); "
        + identity_check
        +
        "print(json.dumps({'state':'CONTAINED','evidence_id':'proof-1',"
        "'evidence_revision':'1','echo':value}))"
    )
    return SlurmContainmentHelper("test-contained-v1", (sys.executable, "-c", program))


def _persist_rejected_slurm_run(run_root: Path, profile: SlurmReadyStageProfile, *, resources=None) -> str:
    run_store = LocalRunStore(run_root)
    run_uri = path_to_run_uri(run_root / "rejected-stage-run")
    run_store.create_run(run_uri)
    pipeline_config = {
        "name": "rejected-stage-run",
        "stages": [
            {
                "name": "train",
                "factory": {
                    "_target_": (
                        "tests.support.pipeline_execution_stages.JsonProducerStage"
                    )
                },
                "config": {"value": 1},
                "outputs": {"data": {"artifact_type": "json", "codec_key": "json.v1"}},
                "placement": {
                    "execution_route": {"kind": "slurm", "profile": "training"}
                },
            }
        ],
    }
    if resources is not None:
        pipeline_config["stages"][0]["resources"] = {"entries": resources.to_dict()["entries"]}
    pipeline = PipelineSpec.from_config(pipeline_config)
    plan = plan_pipeline(
        pipeline,
        run_uri=run_uri,
        stage_state=run_store,
        artifact_index=run_store,
        plans=run_store,
        artifact_store=LocalArtifactStore(run_store.local_artifact_root(run_uri)),
        persist=True,
    )
    run_store.write_runtime_metadata(
        run_uri,
        {"executor": "local", "stages": {"train": {"executor": "local"}}},
    )
    run_store.write_config_snapshot(
        run_uri, "resolved", json_dumps_pretty({"pipeline": pipeline_config})
    )
    prepare_managed_local_runtime_record(
        store=run_store,
        run_uri=run_uri,
        plan=plan,
        pipeline=pipeline,
        execution_requirements=_execution_requirements(pipeline),
        slurm_profiles=(profile,),
    )
    SQLitePerRunAuthorityStore(run_uri).create_run(run_uri, status=RunStatus.RUNNING)
    return run_uri


@pytest.mark.parametrize("conflicting", [False, True])
def test_retained_slurm_worker_is_compared_before_submission_and_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    conflicting: bool,
) -> None:
    from loom.pipeline.execution import prepare_stage_attempt, StageWorkerRequest
    from loom.queue.local_daemon_execution import load_managed_local_intent
    from loom.queue._agent_process_supervisor import AgentProcessSupervisorError
    import loom.queue.local_daemon_execution as execution_owner

    runner = FakeSlurmCommandRunner(starting_job_id=1400)
    profile = _profile(runner, capability_path=tmp_path / "capability")
    run_root = tmp_path / "runs"
    run_uri = _persist_rejected_slurm_run(run_root, profile)
    store = LocalRunStore(run_root)
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=_launch_profile(),
        slurm_profiles=(profile,),
    )
    LocalDaemon.initialize(config)
    intent = load_managed_local_intent(config, run_uri)
    saved = prepare_stage_attempt(
        stage_state=store,
        stage_workspaces=store,
        local_paths=store,
        reliability=store,
        prepared_runs=store,
        config=store,
        run_status=RunStatus.RUNNING,
        run_uri=run_uri,
        stage=intent.pipeline.get_stage("train"),
        stage_plan=intent.plan.ordered_stage_plans[0],
        fingerprint_context=intent.plan.fingerprint_context,
        resolved_runtime=execution_owner._worker_runtime(intent, "train"),
    ).to_dict()
    if conflicting:
        runtime = cast(dict[str, object], saved["resolved_runtime"])
        runtime["resource_policy"] = {"account_for": [], "enforce": []}
        runtime["resource_selection"] = {"account_for": [], "enforce": []}
        StageWorkerRequest.from_dict(saved)
        store.write_stage_worker_request(run_uri, "train", saved, attempt=1)
    request_path = store.local_stage_worker_request_path(run_uri, "train")
    original_bytes, original_mtime = (
        request_path.read_bytes(),
        request_path.stat().st_mtime_ns,
    )
    observed = Event()
    original_compare = execution_owner._require_retained_resource_handoff_match

    def compare(*args, **kwargs):
        try:
            result = original_compare(*args, **kwargs)
        except QueueConflictError as exc:
            assert "differs from placement" in str(exc)
            observed.set()
            raise
        return result

    monkeypatch.setattr(
        execution_owner, "_require_retained_resource_handoff_match", compare
    )
    original_sbatch = runner.sbatch

    def submit(*args, **kwargs):
        result = original_sbatch(*args, **kwargs)
        observed.set()
        return result

    monkeypatch.setattr(runner, "sbatch", submit)
    daemon = LocalDaemon(config)
    daemon.start()
    execution = daemon._execution
    assert execution is not None
    supervisor = execution.supervisor
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
        )
        client.submit(LocalDaemonAdmissionRequest("retained-worker", run_uri))
        assert observed.wait(5), "retained SLURM worker boundary was not reached"
        daemon.stop()
        assert request_path.read_bytes() == original_bytes
        assert request_path.stat().st_mtime_ns == original_mtime
        submissions = [call for call in runner.calls if call[0] == "sbatch"]
        if conflicting:
            assert submissions == []
            assert execution.slurm_assignments.list_run_unreleased(run_uri) == ()
        else:
            assert len(submissions) == 1
            assert len(execution.slurm_assignments.list_run_unreleased(run_uri)) == 1
    finally:
        daemon.stop()
        if supervisor is not None:
            try:
                supervisor.shutdown_for_test()
            except AgentProcessSupervisorError as exc:
                assert str(exc) == "managed supervisor endpoint is unavailable"


def test_slurm_offer_recovery_defers_preparation_and_rechecks_after_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.pipeline._project_contracts as contracts
    from loom.queue.local_daemon_execution import LocalDaemonExecution

    runner = FakeSlurmCommandRunner()
    profile = _profile(runner)
    run_root = tmp_path / "runs"
    run_uri = _persist_rejected_slurm_run(run_root, profile)
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=_launch_profile(),
        slurm_profiles=(profile,),
    )
    available = Event()
    deferred = Event()
    validated = Event()
    original_select = LocalDaemonExecution._select_slurm_agent
    original_metadata = contracts.worker_contract_metadata
    withdraw_on_validation = [True]

    def select(execution, selected):
        if not available.is_set():
            deferred.set()
            raise SlurmPlanningError("slurm_profile_unavailable")
        return original_select(execution, selected)

    def validate(*args, **kwargs):
        # This owner checks the report for both fresh preparation and retained
        # request validation. Withdraw the offer after that actual boundary.
        result = original_metadata(*args, **kwargs)
        if withdraw_on_validation[0]:
            withdraw_on_validation[0] = False
            available.clear()
        validated.set()
        return result

    monkeypatch.setattr(LocalDaemonExecution, "_select_slurm_agent", select)
    monkeypatch.setattr(contracts, "worker_contract_metadata", validate)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        daemon.client_view(
            LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
        ).submit(LocalDaemonAdmissionRequest("offer-recovery", run_uri))
        assert deferred.wait(5)
        store = LocalRunStore(run_root)
        assert store.read_stage_worker_request(run_uri, "train", attempt=None) is None
        assert not validated.is_set()
        deferred.clear()
        available.set()
        assert validated.wait(5)
        assert deferred.wait(5), "offer must be checked again after validation"
        assert not [call for call in runner.calls if call[0] == "sbatch"]
        assert daemon._execution is not None
        assert not daemon._execution.slurm_assignments.list_run_unreleased(run_uri)
        execution = daemon._execution
        available.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if any(call[0] == "sbatch" for call in runner.calls):
                break
            time.sleep(0.02)
        daemon.stop()
        assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1
        assert len(execution.slurm_assignments.list_run_unreleased(run_uri)) == 1
    finally:
        daemon.stop()


@pytest.mark.parametrize("process_policy", [None, "bounded-v1"])
def test_slurm_containment_requires_exact_positive_echo(process_policy) -> None:
    runner = FakeSlurmCommandRunner()
    request = {
        "assignment_id": "assignment-1",
        "profile_id": "training",
        "profile_configuration_fingerprint": "fingerprint",
        "submission_operation_id": "operation-1",
        "cluster_id": "cluster-a",
        "job_id": "1",
        "bootstrap_incarnation_id": "bootstrap-1",
        "process_execution_id": "process-1",
        "execution_fence": "fence-1",
    }
    profile = _profile(runner)
    assert not resolve_slurm_containment(profile, request).contained
    echo_program = (
        "import json,sys; value=json.load(sys.stdin); "
        "print(json.dumps({'state':'CONTAINED','evidence_id':'proof-1','evidence_revision':'1','echo':value}))"
    )
    object.__setattr__(
        profile,
        "containment_helper",
        SlurmContainmentHelper(
            "test-contained-v1", (sys.executable, "-c", echo_program), process_policy=process_policy,
        ),
    )
    assert resolve_slurm_containment(profile, request).contained
    mismatch_program = (
        "import json,sys; value=json.load(sys.stdin); value['job_id']='2'; "
        "print(json.dumps({'state':'CONTAINED','evidence_id':'proof-1','evidence_revision':'1','echo':value}))"
    )
    object.__setattr__(
        profile,
        "containment_helper",
        SlurmContainmentHelper(
            "test-contained-v1", (sys.executable, "-c", mismatch_program), process_policy=process_policy,
        ),
    )
    assert not resolve_slurm_containment(profile, request).contained


@pytest.mark.parametrize("state,version,code,accepted", [
    ("UNKNOWN", 1, "terminal_controller_record_retained", True),
    ("CONTAINED", 1, "terminal_controller_record_retained", False),
    ("UNKNOWN", True, "terminal_controller_record_retained", False),
    ("UNKNOWN", 2, "terminal_controller_record_retained", False),
    ("UNKNOWN", 1, "unrecognized", False),
])
def test_containment_negative_diagnostic_never_proves_release(state, version, code, accepted):
    payload = {"state": state, "diagnostic": {"schema_version": version, "code": code}}
    program = f"print({json.dumps(payload)!r})"
    profile = _profile(FakeSlurmCommandRunner())
    object.__setattr__(profile, "containment_helper", SlurmContainmentHelper(
        "diagnostic-fixture", (sys.executable, "-c", program),
    ))
    receipt = resolve_slurm_containment(profile, {})
    assert not receipt.contained
    assert receipt.diagnostic_code == (code if accepted else None)


def test_slurm_containment_timeout_is_part_of_retained_profile_identity() -> None:
    runner = FakeSlurmCommandRunner()
    helper = SlurmContainmentHelper("site-helper-v1", ("site-helper",), 5.0)
    slower = replace(helper, timeout_seconds=10.0)

    first = replace(_profile(runner), containment_helper=helper)
    second = replace(_profile(runner), containment_helper=slower)

    assert first.configuration_fingerprint != second.configuration_fingerprint


def _agent_observation(execution, *args, **kwargs):
    agent = execution._slurm_agent
    assert agent is not None
    agent.replay_pending(lambda evidence: execution.acknowledge_slurm_agent(
        execution.agent_id, execution.agent_id, evidence,
    ))
    submission = agent.journal._record_observation(*args, **kwargs)
    assignment = execution.slurm_assignments.read_operation(
        submission.request.operation_id
    ).assignment
    agent._publish(
        assignment,
        submission,
        lambda evidence: execution.acknowledge_slurm_agent(
            assignment.agent_id, assignment.agent_root_id, evidence
        ),
    )
    return submission


def _exercise_mixed_route_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    terminal_boundary: str | None = None,
    *,
    finish_during_outage: bool = False,
    long_outage: bool = False,
    accounting_history: bool = False,
    trusted_user: bool = False,
    slurm_output_size: int | None = None,
    lose_output_ack_at: int | None = None,
    guarded_recovery: bool = False,
    provider_retry_state: str | None = None,
    provider_retry_winner: str | None = None,
    prestart_failure: bool = False,
    replayable_start: bool = False,
    recovery_terminal_state: str | None = None,
    native_failure: bool = False,
    container_options: Mapping[str, object] | None = None,
) -> None:
    from datetime import timedelta
    from loom.timestamps import parse_timestamp, utc_timestamp

    now = [utc_timestamp()]
    history_state = ["RUNNING"]
    def clock():
        return now[0] if long_outage else utc_timestamp()

    command_policy = SlurmCommandPolicy(10, 60, 10) if long_outage or accounting_history else None
    runner = FakeSlurmCommandRunner(starting_job_id=1200, command_policy=command_policy)
    containment_helper = _positive_containment_helper(accounting_identity=accounting_history)
    if accounting_history:
        containment_helper = replace(containment_helper, process_policy="bounded-v1")

    def select_history(candidate):
        if not accounting_history:
            return candidate
        from loom.pipeline.executors.slurm.history import SlurmHistoryPolicy
        original = candidate.runner.discover_named_operation
        def observe(**selection):
            result = original(**selection)
            submitted = utc_timestamp(parse_timestamp(selection["started_after"]) + timedelta(seconds=60))[:-1]
            return replace(result, stdout=(
                f"1200|{selection['job_name']}|1000|cluster-a|{submitted}|1200|sFixture1200|{history_state[0]}\n"
            ))
        monkeypatch.setattr(candidate.runner, "discover_named_operation", observe)
        return replace(candidate, accounting_history=SlurmHistoryPolicy(1000))
    profile = _profile(
        runner,
        containment_helper=containment_helper,
        container_options=container_options,
    )
    if trusted_user:
        from loom.pipeline.executors.slurm.trusted_user import SlurmUserPrivateFileProvider
        profile = replace(profile, job_private_file_provider=SlurmUserPrivateFileProvider(
            root=tmp_path / "credentials", descriptor="trusted-test-v1",
        ))
    profile = select_history(profile)

    def capability_path(operation_id):
        provider = profile.job_private_file_provider
        return provider.path_for(operation_id) if trusted_user else Path(provider.fixed_path)

    original_compare_and_set = SQLiteReadyStageSubmissions._compare_and_set
    intent_crash_injected = False

    def crash_after_submission_intent(
        owner: SQLiteReadyStageSubmissions, *args: object, **kwargs: object
    ):
        nonlocal intent_crash_injected
        if not intent_crash_injected:
            intent_crash_injected = True
            raise OSError("simulated crash after durable submission intent")
        return original_compare_and_set(owner, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        SQLiteReadyStageSubmissions,
        "_compare_and_set",
        crash_after_submission_intent,
    )
    run_root = tmp_path / "runs"
    run_store = LocalRunStore(run_root)
    run_uri = path_to_run_uri(run_root / "mixed-run")
    run_store.create_run(run_uri)
    pipeline_config = {
        "name": "mixed-route",
        "stages": [
            {
                "name": "preprocess",
                "factory": {
                    "_target_": "tests.support.pipeline_execution_stages.JsonProducerStage"
                },
                "config": {"value": 42},
                "outputs": {"data": {"artifact_type": "json", "codec_key": "json.v1"}},
            },
            {
                "name": "train",
                "factory": {
                    "_target_": (
                        "tests.support.pipeline_execution_stages.NestedFailureStage"
                        if native_failure
                        else "tests.support.pipeline_execution_stages.TextConsumerStage"
                    )
                },
                "depends_on": ["preprocess"],
                **(
                    {"config": {"output_size": slurm_output_size}}
                    if slurm_output_size is not None
                    else {}
                ),
                "inputs": {"data": "preprocess.data"},
                "outputs": {"text": {"artifact_type": "text", "codec_key": "text.v1"}},
                "placement": {
                    "execution_route": {"kind": "slurm", "profile": "training"}
                },
            },
            {
                "name": "evaluate",
                "factory": {
                    "_target_": "tests.support.pipeline_execution_stages.JsonProducerStage"
                },
                "depends_on": ["train"],
                "inputs": {"unused": "train.text"},
                "config": {"value": 7},
                "outputs": {"data": {"artifact_type": "json", "codec_key": "json.v1"}},
            },
        ],
    }
    pipeline = PipelineSpec.from_config(pipeline_config)
    plan = plan_pipeline(
        pipeline,
        run_uri=run_uri,
        stage_state=run_store,
        artifact_index=run_store,
        plans=run_store,
        artifact_store=LocalArtifactStore(run_store.local_artifact_root(run_uri)),
        persist=True,
    )
    run_store.write_runtime_metadata(
        run_uri,
        {
            "executor": "local",
            "stages": {name: {"executor": "local"} for name in pipeline.stage_names},
        },
    )
    run_store.write_config_snapshot(
        run_uri,
        "resolved",
        json_dumps_pretty({"pipeline": pipeline_config}),
    )
    prepare_managed_local_runtime_record(
        store=run_store,
        run_uri=run_uri,
        plan=plan,
        pipeline=pipeline,
        execution_requirements=_execution_requirements(pipeline),
        slurm_profiles=(profile,),
    )
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    agent_policy = AgentPolicyConfig(
        principals=(
            TransportPrincipalPolicy(
                "operator-credential",
                "operator",
                "operator",
                actions=("recover_unknown", "recover_time") if long_outage else ("recover_unknown",),
            ),
        )
    )
    if replayable_start:
        from loom.queue.agent_sessions import AgentPrincipalPolicy
        agent_policy = replace(agent_policy, agents=(AgentPrincipalPolicy(
            "submit-credential", "submit", "submit", ("default",),
            ("slurm-agent-jobs-v1", "slurm-pending-effects-v1", "slurm-replayable-start-v1"),
        ),))
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "daemon" / "coordinator",
        agent_root=tmp_path / "daemon" / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=_launch_profile(),
        agent_policy=agent_policy,
        slurm_profiles=(profile,),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config, clock=clock)
    daemon.start()
    try:
        original_sbatch = runner.sbatch

        def register_inside_sbatch(*args: object, **kwargs: object):
            execution = daemon._execution
            assert execution is not None
            (retained,) = execution.slurm_assignments.list_run_unreleased(run_uri)
            assert retained.state == "submitting"
            bootstrap = daemon.slurm_bootstrap_view(
                LocalDaemonPrincipal(
                    "slurm-principal",
                    LocalDaemonRole.SLURM_BOOTSTRAP,
                    "slurm-credential",
                )
            )
            bootstrap.register(
                operation_id=retained.assignment.operation_id,
                request_digest=retained.assignment.request_digest,
                job_id="1200",
                cluster="cluster-a",
                incarnation="bootstrap-1",
                capability=base64.b64encode(
                    capability_path(retained.assignment.operation_id).read_bytes()
                ).decode(),
            )
            # A fast compute bootstrap can finish inputs before sbatch responds.
            response = _dispatch_application(
                daemon,
                LocalDaemonPrincipal(
                    "slurm-principal",
                    LocalDaemonRole.SLURM_BOOTSTRAP,
                    "slurm-credential",
                ),
                "slurm_bootstrap",
                "inputs_ready",
                {
                    "assignment_id": retained.assignment.assignment_id,
                    "incarnation": "bootstrap-1",
                },
            )
            assert response == {"state": "awaiting_submission_ack"}
            pending = execution.slurm_assignments.read(
                retained.assignment.assignment_id
            )
            assert pending.state == "submitting"
            assert pending.input_ready is False
            assert pending.fence is None
            with pytest.raises(QueueConflictError, match="durable inputs"):
                bootstrap.grant(retained.assignment.assignment_id, "bootstrap-1")
            return original_sbatch(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(runner, "sbatch", register_inside_sbatch)
        client = daemon.client_view(
            LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
        )
        client.submit(LocalDaemonAdmissionRequest("mixed-route", run_uri))
        execution = daemon._execution
        assert execution is not None
        deadline = time.monotonic() + 45
        records = ()
        while time.monotonic() < deadline:
            records = execution.slurm_assignments.list_run_unreleased(run_uri)
            if records and records[0].state == "accepted":
                break
            time.sleep(0.02)
        assert len(records) == 1
        record = records[0]
        assert record.state == "accepted"
        assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1
        operation = daemon.operation(record.assignment.operation_id)
        assert operation.kind == "slurm_stage_assignment"
        assert operation.state == "accepted"
        assert operation.result is not None
        operation_result = cast(Mapping[str, object], operation.result)
        assert operation_result["assignment_id"] == record.assignment.assignment_id
        assert operation_result["request_digest"] == record.assignment.request_digest
        assert operation_result["submission_state"] == "accepted"
        assert operation_result["job_id"] == "1200"
        waited_operation = daemon.wait_operation(
            record.assignment.operation_id, timeout=0
        )
        assert waited_operation.kind.value == "TIMEOUT"
        # The daemon may prepare inputs between the detail read and zero-timeout
        # wait, so compare the stable operation identity and retained evidence.
        assert waited_operation.operation.operation_id == operation.operation_id
        assert waited_operation.operation.kind == operation.kind
        waited_result = cast(Mapping[str, object], waited_operation.operation.result)
        assert waited_result["assignment_id"] == record.assignment.assignment_id
        assert waited_result["request_digest"] == record.assignment.request_digest
        assert waited_result["submission_state"] == "accepted"

        # A fresh daemon/execution/store and fresh helper binding retain the
        # accepted operation rather than preparing or submitting it again.
        daemon.stop()
        fresh_runner = FakeSlurmCommandRunner(
            scripted_results={"sbatch": [AssertionError("must not submit")]},
            command_policy=command_policy,
        )
        profile = _profile(
            fresh_runner,
            containment_helper=containment_helper,
            container_options=container_options,
        )
        if trusted_user:
            profile = replace(profile, job_private_file_provider=SlurmUserPrivateFileProvider(
                root=tmp_path / "credentials", descriptor="trusted-test-v1",
            ))
        profile = select_history(profile)
        reopened_config = LocalDaemonConfig(
            coordinator_root=tmp_path / "daemon" / "coordinator",
            agent_root=tmp_path / "daemon" / "agent",
            run_store_root=run_root,
            resident_worker_launch_profile=_launch_profile(),
            agent_policy=agent_policy,
            slurm_profiles=(profile,),
        )
        daemon = LocalDaemon(reopened_config, clock=clock)
        daemon.start()
        client = daemon.client_view(
            LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
        )
        execution = daemon._execution
        assert execution is not None
        assert (
            execution.slurm_submissions.read(record.assignment.operation_id).state.value
            == "accepted"
        )
        assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1
        assert not [call for call in fresh_runner.calls if call[0] == "sbatch"]

        before_bootstrap = authority.open_run(run_uri)
        train_before = next(
            stage for stage in before_bootstrap.stages if stage.stage_name == "train"
        )
        assert train_before.status is StageStatus.PENDING

        wrong = daemon.slurm_bootstrap_view(
            LocalDaemonPrincipal(
                "slurm-principal",
                LocalDaemonRole.SLURM_BOOTSTRAP,
                "wrong-credential",
            )
        )
        with pytest.raises(Exception, match="not authorized"):
            wrong.register(
                operation_id=record.assignment.operation_id,
                request_digest=record.assignment.request_digest,
                job_id="1200",
                cluster="cluster-a",
                incarnation="bootstrap-wrong",
                capability=base64.b64encode(b"wrong-capability-material").decode(),
            )

        view = daemon.slurm_bootstrap_view(
            LocalDaemonPrincipal(
                "slurm-principal",
                LocalDaemonRole.SLURM_BOOTSTRAP,
                "slurm-credential",
            )
        )
        incarnation = "bootstrap-1"
        # Keep unrelated scheduler observations out of this no-mutation check.
        # Concurrent registration remains exercised independently below.
        with daemon._cycle_lock:
            submission_before_proof = execution.slurm_submissions.read(
                record.assignment.operation_id
            )
            assignment_before_proof = execution.slurm_assignments.read(
                record.assignment.assignment_id
            )
            with pytest.raises(QueueConflictError, match="capability conflicts"):
                view.register(
                    operation_id=record.assignment.operation_id,
                    request_digest=record.assignment.request_digest,
                    job_id="1200",
                    cluster="cluster-a",
                    incarnation="bootstrap-unproven",
                    capability=base64.b64encode(b"wrong-capability-material").decode(),
                )
            assert (
                execution.slurm_submissions.read(record.assignment.operation_id)
                == submission_before_proof
            )
            assert (
                execution.slurm_assignments.read(record.assignment.assignment_id)
                == assignment_before_proof
            )
        registration = view.register(
            operation_id=record.assignment.operation_id,
            request_digest=record.assignment.request_digest,
            job_id="1200",
            cluster="cluster-a",
            incarnation=incarnation,
            capability=base64.b64encode(
                capability_path(record.assignment.operation_id).read_bytes()
            ).decode(),
        )
        capability = base64.b64encode(
            capability_path(record.assignment.operation_id).read_bytes()
        ).decode()

        def concurrent_registration(candidate_incarnation: str) -> object:
            try:
                return view.register(
                    operation_id=record.assignment.operation_id,
                    request_digest=record.assignment.request_digest,
                    job_id="1200",
                    cluster="cluster-a",
                    incarnation=candidate_incarnation,
                    capability=capability,
                )
            except QueueConflictError as exc:
                return str(exc)

        with ThreadPoolExecutor(max_workers=2) as executor:
            replay, conflict = tuple(
                executor.map(
                    concurrent_registration, (incarnation, "bootstrap-competing")
                )
            )
        assert replay == registration
        assert conflict == "SLURM bootstrap incarnation conflicts"
        assert (
            view.register(
                operation_id=record.assignment.operation_id,
                request_digest=record.assignment.request_digest,
                job_id="1200",
                cluster="cluster-a",
                incarnation=incarnation,
                capability=capability,
            )
            == registration
        )
        with pytest.raises(QueueConflictError, match="capability conflicts"):
            view.register(
                operation_id=record.assignment.operation_id,
                request_digest=record.assignment.request_digest,
                job_id="1200",
                cluster="cluster-a",
                incarnation=incarnation,
                capability=base64.b64encode(b"different-capability-material").decode(),
            )
        assignment_id = cast(str, registration["assignment_id"])
        delivery = SlurmStageDelivery.from_dict(registration["delivery"])
        assert (
            delivery.to_dict()
            == SlurmStageDelivery.from_dict(delivery.to_dict()).to_dict()
        )
        assert (
            delivery.resolved_runtime["resource_selection"]
            == (
                SlurmStageDelivery.from_dict(delivery.to_dict()).resolved_runtime[
                    "resource_selection"
                ]
            )
        )
        legacy = delivery.to_dict()
        legacy["schema_version"] = 3
        legacy_runtime = dict(cast(Mapping[str, PlainData], legacy["resolved_runtime"]))
        legacy_runtime.pop("resource_selection", None)
        legacy_runtime.pop("resource_policy", None)
        legacy["resolved_runtime"] = legacy_runtime
        legacy_bytes = json.dumps(legacy, sort_keys=True)
        calls_before = tuple(runner.calls)
        with pytest.raises(QueueServiceError, match="finish|cancel|prepare"):
            SlurmStageDelivery.from_dict(legacy)
        assert json.dumps(legacy, sort_keys=True) == legacy_bytes
        assert tuple(runner.calls) == calls_before
        assert not (tmp_path / "compute").exists()
        workspace = SlurmBootstrapWorkspace(tmp_path / "compute", assignment_id)
        assert "attempt_input_evidence" in delivery.worker_metadata
        assert "attempt_input_bindings" not in delivery.worker_metadata
        assert delivery.worker_metadata["attempt_input_evidence"] == SlurmStageDelivery.from_dict(delivery.to_dict()).worker_metadata["attempt_input_evidence"]
        workspace.persist_delivery(delivery)
        for item in delivery.inputs:
            offset = 0
            while True:
                data, final = view.input_chunk(
                    assignment_id,
                    incarnation,
                    item.transfer_id,
                    offset=offset,
                )
                offset = workspace.stage_input_chunk(
                    item.transfer_id, offset, data, final=final
                )
                if final:
                    break
        workspace.accept_inputs()
        assert _dispatch_application(
            daemon,
            LocalDaemonPrincipal(
                "slurm-principal", LocalDaemonRole.SLURM_BOOTSTRAP, "slurm-credential"
            ),
            "slurm_bootstrap",
            "inputs_ready",
            {"assignment_id": assignment_id, "incarnation": incarnation},
        ) == {"state": "input_ready"}
        fence = view.grant(assignment_id, incarnation)
        if replayable_start:
            assert "slurm-replayable-start-v1" in view.handshake()["capabilities"]
            payload = dict(assignment_id=assignment_id, incarnation=incarnation, fence=fence, request_id="live-process")
            principal = LocalDaemonPrincipal("slurm-principal", LocalDaemonRole.SLURM_BOOTSTRAP, "slurm-credential")
            assert _dispatch_application(daemon, principal, "slurm_bootstrap", "start", payload) == {"permitted": True}
            daemon.stop()
            daemon = LocalDaemon(reopened_config, clock=clock)
            daemon.start()
            view = daemon.slurm_bootstrap_view(principal)
            assert _dispatch_application(daemon, principal, "slurm_bootstrap", "start", payload) == {"permitted": True}
            assert _dispatch_application(daemon, principal, "slurm_bootstrap", "start", {**payload, "request_id": "restarted-process"}) == {"permitted": False}
        else:
            assert view.start_permit(assignment_id, incarnation, fence) is True
        assert view.start_permit(assignment_id, incarnation, fence) is False
        from loom.queue._slurm_start import intended_execution_id
        process_id = intended_execution_id(assignment_id, incarnation) if prestart_failure else "slurm-root-process-1"
        if not prestart_failure:
            view.started(
                assignment_id,
                incarnation,
                fence,
                "slurm-root-process-1",
            )
            execution = daemon._execution
            assert execution is not None
            assert (
                execution.slurm_assignments.read(assignment_id).process_execution_id
                == "slurm-root-process-1"
            )
            with pytest.raises(QueueConflictError, match="process execution identity"):
                view.started(
                    assignment_id,
                    incarnation,
                    fence,
                    "slurm-root-process-2",
                )
        else:
            execution = daemon._execution
            assert execution is not None
            assert execution.slurm_assignments.read(assignment_id).process_execution_id is None
        if provider_retry_state is not None:
            from loom.pipeline.executors.slurm.ready_stage import SlurmContainmentReceipt
            from loom.queue import _agent_slurm
            from loom.queue._continuation import ContinuationPending
            from loom.queue._slurm_retry import PROVIDER_RECOVERY_PREFIX, reconcile

            with daemon._cycle_lock:
                assert reconcile(execution, run_uri) == ContinuationPending("waiting_for_slurm_termination_evidence")
                if provider_retry_state == "TIMEOUT":
                    observed = execution.slurm_submissions.find(record.assignment.operation_id)
                    live = replace(observed, scheduler_state="RUNNING", scheduler_source="squeue",
                                   scheduler_observed_at="2026-01-02T10:00:00Z")
                    with monkeypatch.context() as patch:
                        patch.setattr(execution.slurm_submissions, "find", lambda _: live)
                        assert reconcile(execution, run_uri, accepted_at="2026-01-02T09:59:59Z") is None
                        assert reconcile(
                            execution, run_uri, accepted_at="2026-01-02T10:00:01Z",
                        ) == ContinuationPending("waiting_for_slurm_termination_evidence")
                agent = execution._slurm_agent

                def acknowledge(evidence):
                    return execution.acknowledge_slurm_agent(
                        record.assignment.agent_id, record.assignment.agent_root_id, evidence,
                    )

                with agent._lock:
                    # Replay any earlier observation before injecting a new one.
                    agent.replay_pending(acknowledge)
                    history_state[0] = provider_retry_state
                    observed = agent.journal.observe(record.assignment.operation_id, profile)
                    assert observed.scheduler_source == "sacct" and observed.accounting_identity is not None
                    agent._publish(record.assignment, observed, acknowledge)
                with monkeypatch.context() as patch:
                    patch.setattr(_agent_slurm, "resolve_slurm_containment", lambda *_: SlurmContainmentReceipt("UNKNOWN"))
                    for _ in range(2):
                        assert reconcile(execution, run_uri) == ContinuationPending("waiting_for_slurm_containment_evidence")
                assert not daemon._recovery_fences_ordinary_terminal(assignment_id)
                with daemon._connection() as conn:
                    (intent,) = conn.execute("SELECT recovery_id, state FROM recovery_operations").fetchall()
                assert intent["recovery_id"].startswith(PROVIDER_RECOVERY_PREFIX)
                assert intent["state"] == "pending"
                assert execution.slurm_assignments.read(assignment_id).state == "running"
                if provider_retry_winner == "cancellation":
                    assert client.cancel("mixed-route").cancellation_operation_id is not None
                elif provider_retry_winner == "worker":
                    from loom.queue._slurm_result_transport import SharedSlurmResult
                    result = execute_resident_stage_worker_request(
                        worker_request=workspace.worker_request(), workspace_root=workspace.root,
                        process_containment_owner=ProcessContainmentOwner.OUTER_BOUNDARY,
                    )
                    ordinary = workspace.retain_result(result)
                    transport = SharedSlurmResult(profile.result_storage, assignment_id)
                    identity = execution.slurm_result_identity(execution.slurm_assignments.read(assignment_id))
                    transport.publish(identity, ordinary, workspace.output_chunk)
                    assert transport.deliver(identity, lambda evidence: execution.acknowledge_slurm_agent(
                        execution.agent_id, execution.agent_id, evidence,
                    ))
            daemon.stop()
            daemon = LocalDaemon(config, clock=clock)
            daemon.start()
            execution = daemon._execution
            expected = "CANCELLED" if provider_retry_state == "CANCELLED" else "FAILED"
            if provider_retry_winner is not None:
                expected = "SUCCEEDED" if provider_retry_winner == "worker" else "CANCELLED"
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if (execution.slurm_assignments.read(assignment_id).state == "released"
                    and daemon.admission_for_run_uri(run_uri).state.value == expected):
                    break
                time.sleep(0.02)
            assert daemon.admission_for_run_uri(run_uri).state.value == expected
            train = next(stage for stage in authority.open_run(run_uri).stages if stage.stage_name == "train")
            attempt = train.attempts[-1]
            assert attempt.status.value == expected
            settled = execution.slurm_assignments.read(assignment_id)
            assert settled.state == "released"
            if provider_retry_winner is None:
                assert provider_retry_state in attempt.reason.message
                assert attempt.reason.detail["recovery_id"] == intent["recovery_id"]
                assert settled.report is None
                assert daemon._recovery_fences_ordinary_terminal(assignment_id)
            else:
                assert not daemon._recovery_fences_ordinary_terminal(assignment_id)
                assert (settled.report is not None) == (provider_retry_winner == "worker")
                assert attempt.reason is None or attempt.reason.detail.get("recovery_id") is None
            assert reconcile(execution, run_uri) is None
            assert not capability_path(record.assignment.operation_id).exists()
            return
        recovery_receipt = None
        if guarded_recovery:
            before_recovery = authority.open_run(run_uri)
            train = next(
                item for item in before_recovery.stages if item.stage_name == "train"
            )
            attempt = next(
                item
                for item in train.attempts
                if item.attempt_id == record.assignment.attempt_id
            )
            recovery_request = RecoverUnknownAssignment(
                recovery_id="slurm-recovery-1",
                run_uri=run_uri,
                stage_name=record.assignment.stage_name,
                attempt=record.assignment.attempt,
                stage_work_id=record.assignment.stage_work_id,
                assignment_id=assignment_id,
                process_execution_id=process_id,
                execution_fence=fence,
                target=SlurmRecoveryTarget(
                    profile.profile_id,
                    record.assignment.operation_id,
                    "cluster-a",
                    "1200",
                    incarnation,
                ),
                expected_state_version=attempt.revision.sequence,
                requested_outcome="failed" if recovery_terminal_state else "cancelled",
                consider_retry=recovery_terminal_state is None,
                reason="SLURM containment integration proof",
            )
            operator = daemon.operator_view(
                LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
            )
            with daemon._cycle_lock:
                _agent_observation(
                    execution,  # noqa: SLF001
                    record.assignment.operation_id,
                    expected_job_id="1200",
                    scheduler_state="RUNNING",
                    scheduler_source="squeue",
                    observed_at="2030-01-01T00:00:00+00:00",
                )
                with pytest.raises(
                    QueueConflictError, match="not in an exact unknown state"
                ):
                    operator.recover_unknown(
                        replace(
                            recovery_request,
                            recovery_id="slurm-active-recovery",
                            reason="must not close an observed running job",
                        )
                    )
                with sqlite3.connect(config.control_database) as conn:
                    assert (
                        conn.execute(
                            "SELECT COUNT(*) FROM recovery_operations"
                        ).fetchone()[0]
                        == 0
                    )
                assert not daemon._recovery_fences_ordinary_terminal(  # noqa: SLF001
                    assignment_id
                )

                if not accounting_history:
                    _agent_observation(
                        execution, record.assignment.operation_id,
                        expected_job_id="1200", scheduler_state="TIMEOUT",
                        scheduler_source="sacct", observed_at="2030-01-01T00:00:01+00:00",
                    )
                    with pytest.raises(QueueConflictError, match="not in an exact unknown state"):
                        operator.recover_unknown(replace(recovery_request, recovery_id="no-accounting-identity"))

                with pytest.raises(QueueConflictError, match="identity conflicts"):
                    operator.recover_unknown(replace(
                        recovery_request, recovery_id="wrong-incarnation",
                        target=replace(recovery_request.target, bootstrap_incarnation_id="other-incarnation"),
                    ))
                with pytest.raises(QueueConflictError, match="expected state conflicts"):
                    operator.recover_unknown(replace(
                        recovery_request, recovery_id="stale-revision",
                        expected_state_version=recovery_request.expected_state_version + 1,
                    ))

                unknown_observation = _agent_observation(
                    execution,  # noqa: SLF001
                    record.assignment.operation_id,
                    expected_job_id="1200",
                    scheduler_state=recovery_terminal_state,
                    scheduler_source="sacct" if recovery_terminal_state else "unavailable",
                    observed_at="2030-01-01T00:00:01+00:00",
                )
                assert unknown_observation.scheduler_source == (
                    "sacct" if recovery_terminal_state else "unavailable"
                )
                assert unknown_observation.scheduler_state == recovery_terminal_state
                if recovery_terminal_state is not None:
                    history_state[0] = recovery_terminal_state
                    import loom.queue._agent_slurm as agent_module
                    from loom.pipeline.executors.slurm.ready_stage import SlurmContainmentReceipt
                    with monkeypatch.context() as pending_patch:
                        pending_patch.setattr(agent_module, "resolve_slurm_containment", lambda *_: SlurmContainmentReceipt("UNKNOWN"))
                        pending = operator.recover_unknown(recovery_request)
                        assert pending["state"] == "pending"
                        assert execution.slurm_assignments.read(assignment_id).state == ("granted" if prestart_failure else "running")
                recovery_receipt = operator.recover_unknown(recovery_request)
                assert recovery_receipt["state"] == "closed"
                assert operator.recover_unknown(recovery_request) == recovery_receipt
                assert recovery_receipt["retry_allowed"] is (False if recovery_terminal_state is None else None)
                assert recovery_receipt["physical_ownership"] == "retained"
                recovery_evidence = cast(
                    dict[str, object], recovery_receipt["evidence"]
                )
                assert recovery_evidence["kind"] == "slurm_helper"
                assert recovery_evidence["helper_descriptor"] == "test-contained-v1"
                assert (
                    authority.open_run(run_uri).stages[1].status
                    is (StageStatus.FAILED if recovery_terminal_state else StageStatus.CANCELLED)
                )
                if recovery_terminal_state == "TIMEOUT":
                    with pytest.raises(QueueConflictError, match="identity conflicts"):
                        execution.reconcile_closed_slurm_recovery(
                            replace(recovery_request, execution_fence="different-fence"), recovery_evidence,
                        )
                    with pytest.raises(QueueConflictError, match="exact authority close"):
                        execution.reconcile_closed_slurm_recovery(
                            replace(recovery_request, recovery_id="different-close"), recovery_evidence,
                        )
                    with pytest.raises(QueueConflictError, match="evidence conflicts"):
                        execution.reconcile_closed_slurm_recovery(
                            recovery_request, {**recovery_evidence, "echo": {}},
                        )
                    assert execution.slurm_assignments.read(assignment_id).state == ("granted" if prestart_failure else "running")
                import loom.queue._agent_slurm as agent_module
                from loom.pipeline.executors.slurm.ready_stage import SlurmContainmentReceipt

                original_containment = agent_module.resolve_slurm_containment
                monkeypatch.setattr(agent_module, "resolve_slurm_containment", lambda *_: SlurmContainmentReceipt("UNKNOWN"))
                daemon._resume_pending_recoveries(execution)
                retained = execution.slurm_assignments.read(assignment_id)
                assert retained.state == "logical_released"
                assert capability_path(record.assignment.operation_id).exists()
                assert execution._slurm_task(retained)["result_identity"] is None
                with pytest.raises(QueueConflictError, match="frozen by guarded recovery"):
                    execution.acknowledge_slurm_agent(
                        retained.assignment.agent_id, retained.assignment.agent_root_id,
                        {"assignment_id": assignment_id, "result_operation": "commit"},
                    )
            # Restart with release still unresolved. Closure must replay even
            # when its failed admission is no longer in the active-run scan.
            daemon.stop()
            daemon = LocalDaemon(config, clock=clock)
            daemon.start()
            execution = daemon._execution
            assert execution is not None
            assert execution.slurm_assignments.read(assignment_id).state == "logical_released"
            assert capability_path(record.assignment.operation_id).exists()
            monkeypatch.setattr(agent_module, "resolve_slurm_containment", original_containment)
            deadline = time.monotonic() + 10
            while execution.slurm_assignments.read(assignment_id).state != "released":
                assert time.monotonic() < deadline, "contained recovery release did not settle"
                time.sleep(0.02)
            assert not execution.slurm_assignments.list_run_unreleased(run_uri)
            assert not capability_path(record.assignment.operation_id).exists()
            assert execution.slurm_assignments.read(assignment_id).report is None
            if prestart_failure:
                assert execution.slurm_assignments.read(assignment_id).process_execution_id is None
            assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1
            operator = daemon.operator_view(LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR))
            assert operator.recover_unknown(recovery_request) == recovery_receipt
            assert daemon._recovery_fences_ordinary_terminal(assignment_id)
            return
        if finish_during_outage:
            from loom.queue.local_daemon_execution import LocalDaemonExecution
            from loom.queue._slurm_result_transport import SharedSlurmResult

            identity = execution.slurm_result_identity(
                execution.slurm_assignments.read(assignment_id)
            )
            with pytest.raises(QueueConflictError, match="another submit agent"):
                execution.relay_slurm_result(
                    "foreign-agent",
                    "foreign-root",
                    {
                        "assignment_id": assignment_id,
                        "identity": identity,
                        "result_operation": "commit",
                    },
                )
            before_outage = daemon.status()
            daemon.stop()
            # This is an actual compute process. It gets no coordinator transport
            # and terminates before the submit agent/coordinator are reopened.
            program = """
import json, sys
from loom.queue.slurm_ready_stage import SlurmBootstrapWorkspace
from loom.queue._slurm_result_transport import SharedSlurmResult
from loom.pipeline.execution.stage_worker import execute_resident_stage_worker_request
from loom.pipeline.context import ProcessContainmentOwner
identity = json.loads(sys.argv[3])
workspace = SlurmBootstrapWorkspace(sys.argv[1], identity['assignment']['assignment_id'])
result = execute_resident_stage_worker_request(worker_request=workspace.worker_request(), workspace_root=workspace.root, process_containment_owner=ProcessContainmentOwner.OUTER_BOUNDARY)
report = workspace.retain_result(result)
SharedSlurmResult(json.loads(sys.argv[2]), report.assignment_id, compute=True).publish(identity, report, workspace.output_chunk)
"""
            assert profile.result_storage is not None
            completed_compute = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    program,
                    str(tmp_path / "compute"),
                    json.dumps(dict(profile.result_storage)),
                    json.dumps(identity),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert completed_compute.returncode == 0, completed_compute.stderr
            shutil.rmtree(tmp_path / "compute")
            retained = SharedSlurmResult(profile.result_storage, assignment_id)
            retained_report, output_bytes = retained.read(identity)
            assert retained_report.schema_version == 6
            assert output_bytes
            if slurm_output_size is not None:
                assert sum(map(len, output_bytes.values())) == slurm_output_size
            assert execution.slurm_assignments.read(assignment_id).state == ("granted" if prestart_failure else "running")
            commits = []
            output_ack_lost = Event()
            output_acknowledgements = []
            original_finalize = LocalDaemonExecution._slurm_finalize_record
            original_relay = LocalDaemonExecution.relay_slurm_result

            def lose_output_ack(owner, agent_id, agent_root_id, evidence, **verification):
                response = original_relay(owner, agent_id, agent_root_id, evidence, **verification)
                if evidence.get("result_operation") == "output":
                    output_acknowledgements.append(
                        (evidence["offset"], response["received"])
                    )
                    if (
                        lose_output_ack_at is not None
                        and response["received"] == lose_output_ack_at
                        and not output_ack_lost.is_set()
                    ):
                        assert not commits
                        assert retained.path.exists()
                        assert (
                            owner.slurm_assignments.read(assignment_id).state
                            == "running"
                        )
                        output_ack_lost.set()
                        raise OSError(
                            "lost persisted output acknowledgement before commit"
                        )
                return response

            def lose_first_ack(owner, candidate, candidate_fence, **verification):
                if lose_output_ack_at is not None:
                    assert output_ack_lost.is_set()
                original_finalize(owner, candidate, candidate_fence, **verification)
                committed = next(
                    stage.latest_commit
                    for stage in owner._remote_authority(run_uri)
                    .open_run(run_uri)
                    .stages
                    if stage.stage_name == "train"
                )
                assert committed is not None
                commits.append(committed.commit_id)
                if lose_output_ack_at is None and len(commits) == 1:
                    assert retained.path.exists()
                    raise OSError("lost final result acknowledgement")

            monkeypatch.setattr(
                LocalDaemonExecution, "_slurm_finalize_record", lose_first_ack
            )
            monkeypatch.setattr(
                LocalDaemonExecution, "relay_slurm_result", lose_output_ack
            )
            if long_outage:
                now[0] = utc_timestamp(parse_timestamp(now[0]) + timedelta(hours=8))
            daemon = LocalDaemon(reopened_config, clock=clock)
            daemon.start()
            if long_outage:
                # The result belongs to an execution granted before both the
                # ordinary restart and the explicit clock-recovery epoch.
                with daemon._cycle_lock:
                    with pytest.raises(QueueServiceError, match="degraded|step"):
                        daemon._accepted_snapshot()
                degraded = daemon.status()
                assert degraded.accepted_time_health == "degraded"
                assert not degraded.scheduling_ready
                assert degraded.coordinator_epoch != before_outage.coordinator_epoch
                operator = daemon.operator_view(
                    LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
                )
                recovery = TimeRecoveryRequest(
                    "recover-after-outage", degraded.accepted_time_revision,
                    degraded.coordinator_epoch, "operator verified the site clock",
                )
                receipt = operator.recover_time(recovery)
                assert receipt.previous_coordinator_epoch == degraded.coordinator_epoch
                assert receipt.coordinator_epoch != degraded.coordinator_epoch
                assert receipt.recovered_at == now[0]
                assert operator.recover_time(recovery) == receipt
                assert daemon.status().accepted_time_health == "healthy"
            client = daemon.client_view(
                LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
            )
            settled = client.wait("mixed-route", timeout_seconds=20)
            assert settled.state is LocalDaemonAdmissionState.SUCCEEDED
            assert len(commits) >= (2 if lose_output_ack_at is None else 1)
            assert len(set(commits)) == 1
            if lose_output_ack_at is not None:
                assert output_ack_lost.is_set()
                if slurm_output_size == 0:
                    assert output_acknowledgements == [(0, 0), (0, 0)]
                else:
                    assert output_acknowledgements[:3] == [
                        (0, 32768),
                        (32768, 65536),
                        (0, 65536),
                    ]
                    if slurm_output_size == 98304:
                        assert output_acknowledgements[3:] == [(65536, 98304)]
                    else:
                        assert len(output_acknowledgements) == 3
            saved_result = run_store.read_stage_worker_result(
                run_uri, "train", attempt=1
            )
            assert saved_result is not None
            from loom.io.uris import uri_to_path
            from loom.pipeline.execution.models import StageWorkerResult

            saved_outputs = StageWorkerResult.from_dict(saved_result).outputs
            for artifact in retained_report.outputs:
                ref = saved_outputs[artifact.logical_name]
                assert (
                    uri_to_path(ref.uri).read_bytes()
                    == output_bytes[artifact.transfer_id]
                )
            assert not retained.path.exists()
            assert daemon._execution is not None
            assert (
                daemon._execution.slurm_assignments.read(assignment_id).state
                == "released"
            )
            if accounting_history:
                submission = daemon._execution.slurm_submissions.read(record.assignment.operation_id)
                assert submission.schema_version == 4
                assert submission.accounting_identity.db_index == "1200"
                assert submission.accounting_identity.sluid == "sFixture1200"
            replayed_view = daemon.slurm_bootstrap_view(
                LocalDaemonPrincipal(
                    "slurm-principal", LocalDaemonRole.SLURM_BOOTSTRAP,
                    "slurm-credential",
                )
            )
            assert replayed_view.grant(assignment_id, incarnation) == fence
            assert replayed_view.start_permit(assignment_id, incarnation, fence) is False
            assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1
            assert not [call for call in fresh_runner.calls if call[0] == "sbatch"]
            return
        worker_result = execute_resident_stage_worker_request(
            worker_request=workspace.worker_request(),
            workspace_root=workspace.root,
            process_containment_owner=ProcessContainmentOwner.OUTER_BOUNDARY,
        )
        report = workspace.retain_result(worker_result)
        assert report.schema_version == 6
        assert report.process_created is True
        assert report.resource_controls is not None
        assert {
            "resource": "cpu",
            "owner": "slurm",
            "mechanism": "sbatch_allocation",
            "disposition": "delegated",
        } in report.resource_controls
        view.declare_report(assignment_id, incarnation, fence, report)
        original_publish = slurm_ready_stage._publish_staged_file
        crash_injected = False
        for output in report.outputs:
            offset = 0
            while True:
                data, final = workspace.output_chunk(output.transfer_id, offset)
                if final and not crash_injected:
                    crash_injected = True

                    def publish_then_crash(staging: Path, target: Path) -> None:
                        original_publish(staging, target)
                        raise OSError("simulated post-publish crash")

                    monkeypatch.setattr(
                        slurm_ready_stage,
                        "_publish_staged_file",
                        publish_then_crash,
                    )
                    with pytest.raises(OSError, match="post-publish crash"):
                        view.output_chunk(
                            assignment_id,
                            incarnation,
                            output.transfer_id,
                            offset=offset,
                            data=data,
                            final=True,
                        )
                    monkeypatch.setattr(
                        slurm_ready_stage,
                        "_publish_staged_file",
                        original_publish,
                    )
                offset = view.output_chunk(
                    assignment_id,
                    incarnation,
                    output.transfer_id,
                    offset=offset,
                    data=data,
                    final=final,
                )
                if final:
                    break
        if terminal_boundary is None:
            view.commit_result(assignment_id, incarnation, fence)
            view.release(assignment_id, incarnation)

            # A bootstrap restart may replay retained evidence, but the consumed
            # root-launch permit never becomes available again.
            replayed = SlurmBootstrapWorkspace(tmp_path / "compute", assignment_id)
            assert replayed.retained_report() == report
            view.inputs_ready(assignment_id, incarnation)
            assert view.grant(assignment_id, incarnation) == fence
            assert view.start_permit(assignment_id, incarnation, fence) is False
            view.declare_report(assignment_id, incarnation, fence, report)
            for output in report.outputs:
                data, final = replayed.output_chunk(output.transfer_id, 0)
                assert final is True
                assert (
                    view.output_chunk(
                        assignment_id,
                        incarnation,
                        output.transfer_id,
                        offset=0,
                        data=data,
                        final=True,
                    )
                    == output.size_bytes
                )
            view.commit_result(assignment_id, incarnation, fence)
            view.release(assignment_id, incarnation)

            completed = client.wait("mixed-route", timeout_seconds=10)
            if native_failure:
                assert completed.state is LocalDaemonAdmissionState.FAILED
                assert report.schema_version == 6
                assert report.failure is not None
                saved_failure = run_store.read_stage_failure(run_uri, "train")
                assert saved_failure is not None
                assert saved_failure["run_uri"] == run_uri
                assert saved_failure["details"] == report.failure.to_dict()["details"]
                saved_text = json.dumps(saved_failure)
                assert "could not prepare the experiment input" in saved_text
                assert "missing /worker/data/product.json" in saved_text
                assert "Prepare the product on the selected worker." in saved_text
                saved_result = run_store.read_stage_worker_result(
                    run_uri, "train", attempt=1
                )
                assert saved_result is not None
                assert saved_result["failure"] == saved_failure
                assert authority.open_run(run_uri).status is RunStatus.FAILED
                assert (
                    execution.slurm_assignments.read(assignment_id).state == "released"
                )
                assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1
                return
            assert completed.state is LocalDaemonAdmissionState.SUCCEEDED
            released_operation = daemon.wait_operation(
                record.assignment.operation_id, timeout=2
            )
            assert released_operation.kind.value == "TERMINAL"
            assert released_operation.operation.state == "released"
            assert released_operation.operation.result is not None
            released_result = cast(
                Mapping[str, object], released_operation.operation.result
            )
            assert released_result["loom_result_status"] == "SUCCEEDED"
            snapshot = authority.open_run(run_uri)
            assert snapshot.status is RunStatus.SUCCEEDED
            assert [stage.status for stage in snapshot.stages] == [
                StageStatus.SUCCEEDED,
                StageStatus.SUCCEEDED,
                StageStatus.SUCCEEDED,
            ]
            assert execution.slurm_assignments.read(assignment_id).state == "released"
            if container_options is not None:
                saved_result = run_store.read_stage_worker_result(
                    run_uri, "train", attempt=1
                )
                assert saved_result is not None
                metadata = cast(Mapping[str, object], saved_result["executor_metadata"])
                assert (
                    cast(Mapping[str, object], metadata["request"])["executor_name"]
                    == "local"
                )
                scheduler = cast(Mapping[str, object], metadata["scheduler"])
                assert scheduler["mode"] == "ready"
                assert scheduler["job_id"] == record.job_id
                assert scheduler["input_ready"] is True
                assert scheduler["agent_id"] == record.assignment.agent_id
                assert (
                    scheduler["submission_operation_id"]
                    == record.assignment.operation_id
                )
                assert scheduler["agent_evidence_accepted_at"] is not None
                observation = cast(Mapping[str, object], scheduler["observation"])
                assert "scheduler_source" in observation
                assert (
                    execution.slurm_assignments.read(assignment_id).input_ready is True
                )
                assert str(tmp_path) not in json.dumps(metadata)
                container = cast(Mapping[str, object], metadata["container"])
                assert container["container_runtime"] == "apptainer"
                assert "/fixture/bootstrap.json" not in json.dumps(container)
                assert str(
                    profile.job_private_file_provider.fixed_path
                ) not in json.dumps(container)
            script = (
                cast(Path, config.agent_root)
                / "slurm-scripts"
                / f"{record.assignment.assignment_id}.sh"
            ).read_text(encoding="utf-8")
            assert run_uri not in script
            assert profile.credential_reference not in script
            assert "TextConsumerStage" not in script
            assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1
            return

        original_mark_terminal = execution.slurm_assignments.mark_terminal
        terminal_crash_injected = False

        def mark_terminal_at_crash_boundary(candidate_assignment_id: str) -> None:
            nonlocal terminal_crash_injected
            if terminal_boundary == "authority_result" and not terminal_crash_injected:
                terminal_crash_injected = True
                raise OSError("simulated crash after authority result commit")
            if (
                terminal_boundary == "assignment_terminal"
                and not terminal_crash_injected
            ):
                retained = execution.slurm_assignments.read(candidate_assignment_id)
                execution.slurm_assignments.advance(
                    candidate_assignment_id,
                    expected=retained.state,
                    next_state="terminal",
                )
                terminal_crash_injected = True
                raise OSError("simulated crash after assignment terminal commit")
            original_mark_terminal(candidate_assignment_id)

        revoke_calls = 0
        provider_class = type(profile.job_private_file_provider)
        original_revoke = provider_class.revoke

        def revoke_with_lost_response(
            provider: SlurmJobPrivateFileProvider, prepared: object
        ) -> None:
            nonlocal revoke_calls
            revoke_calls += 1
            original_revoke(provider, prepared)  # type: ignore[arg-type]
            if revoke_calls == 1:
                raise SlurmPlanningError("simulated lost revoke acknowledgement")

        monkeypatch.setattr(
            execution.slurm_assignments,
            "mark_terminal",
            mark_terminal_at_crash_boundary,
        )
        monkeypatch.setattr(
            provider_class, "revoke", revoke_with_lost_response
        )
        execution._launch_lock.acquire()
        try:
            with pytest.raises(OSError, match="simulated crash"):
                view.commit_result(assignment_id, incarnation, fence)
        finally:
            monkeypatch.setattr(
                execution.slurm_assignments, "mark_terminal", original_mark_terminal
            )
            execution._launch_lock.release()

        deadline = time.monotonic() + 10
        while (
            execution.slurm_assignments.read(assignment_id).state != "released"
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        assert revoke_calls >= 2, daemon.status()
        assert execution.slurm_assignments.read(assignment_id).state == "released"
        assert not capability_path(record.assignment.operation_id).exists()
        assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1
    finally:
        daemon.stop()


def test_mixed_route_run_uses_one_slurm_submit_and_verified_loom_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _exercise_mixed_route_run(tmp_path, monkeypatch)


def test_selected_container_ready_run_persists_redacted_receipt_after_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _exercise_mixed_route_run(
        tmp_path,
        monkeypatch,
        container_options={
            "image": {"reference": "/private/analysis.sif"},
            "mounts": [
                {
                    "source": str(_RESULT_ROOT.parent / "capability"),
                    "target": str(_RESULT_ROOT.parent / "capability"),
                    "mode": "rw",
                }
            ],
            "environment": {"required_host_variables": ["LOOM_SLURM_BOOTSTRAP_CONFIG"]},
        },
    )


def test_slurm_native_failure_retains_portable_cause_through_result_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _exercise_mixed_route_run(tmp_path, monkeypatch, native_failure=True)


def test_slurm_guarded_recovery_closes_then_releases_from_exact_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _exercise_mixed_route_run(tmp_path, monkeypatch, guarded_recovery=True)


@pytest.mark.parametrize("state", ["TIMEOUT", "PREEMPTED", "NODE_FAIL", "OUT_OF_MEMORY", "CANCELLED"])
def test_retry_reconciles_contained_slurm_outcome_and_waits_for_release(tmp_path, monkeypatch, state):
    _exercise_mixed_route_run(tmp_path, monkeypatch, provider_retry_state=state, accounting_history=True)


@pytest.mark.parametrize("winner", ["worker", "cancellation"])
def test_retry_honours_ordinary_winner_before_provider_close(tmp_path, monkeypatch, winner):
    _exercise_mixed_route_run(tmp_path, monkeypatch, provider_retry_state="TIMEOUT",
                              accounting_history=True, provider_retry_winner=winner)


@pytest.mark.parametrize("terminal_state", ["TIMEOUT", "FAILED", "CANCELLED", "COMPLETED"])
def test_terminal_without_report_uses_guarded_recovery(tmp_path, monkeypatch, terminal_state):
    _exercise_mixed_route_run(
        tmp_path, monkeypatch, guarded_recovery=True,
        accounting_history=True, recovery_terminal_state=terminal_state,
    )


@pytest.mark.parametrize(
    "terminal_boundary",
    ["authority_result", "assignment_terminal"],
)
@pytest.mark.parametrize("trusted_user", [False, True])
def test_terminal_slurm_result_reconciliation_releases_after_crash_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, terminal_boundary: str, trusted_user: bool,
) -> None:
    _exercise_mixed_route_run(tmp_path, monkeypatch, terminal_boundary, trusted_user=trusted_user)


@pytest.mark.parametrize(
    ("boundary", "expected_state", "authority_bound", "capability_retained"),
    (
        ("submission_rejected", "submitting", True, True),
        ("assignment_rejected", "rejected", True, True),
        ("authority_unbound", "rejected", False, True),
        ("logical_released", "logical_released", False, True),
        ("provider_revoked", "logical_released", False, False),
        ("final_released", "released", False, False),
    ),
)
def test_definite_slurm_rejection_restarts_after_every_release_arrow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    expected_state: str,
    authority_bound: bool,
    capability_retained: bool,
) -> None:
    capability_path = tmp_path / "job-private-capability"
    runner = FakeSlurmCommandRunner(
        scripted_results={"sbatch": [SlurmCommandResult("sbatch", ("sbatch",), 1)]}
    )
    profile = _profile(runner, capability_path=capability_path)
    run_root = tmp_path / "runs"
    run_uri = _persist_rejected_slurm_run(run_root, profile)
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "daemon" / "coordinator",
        agent_root=tmp_path / "daemon" / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=_launch_profile(),
        slurm_profiles=(profile,),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    runtime = daemon._thread  # noqa: SLF001
    daemon._stop.set()  # noqa: SLF001
    daemon._wake.set()  # noqa: SLF001
    assert runtime is not None
    runtime.join(timeout=5)
    assert not runtime.is_alive()
    daemon._thread = None  # noqa: SLF001
    execution = daemon._execution  # noqa: SLF001
    assert execution is not None
    injected = False

    with monkeypatch.context() as context:
        if boundary == "submission_rejected":
            original_record = execution.slurm_assignments.record_submission

            def crash_before_assignment_rejection(
                assignment_id: str,
                *,
                state: str,
                job_id: str | None,
                cluster: str | None,
            ) -> str:
                nonlocal injected
                if state == "rejected" and not injected:
                    injected = True
                    raise OSError("crash after rejected submission")
                return original_record(
                    assignment_id, state=state, job_id=job_id, cluster=cluster
                )

            context.setattr(
                execution.slurm_assignments,
                "record_submission",
                crash_before_assignment_rejection,
            )
        elif boundary in {"assignment_rejected", "authority_unbound"}:
            original_unbind = SQLitePerRunAuthorityStore.unbind_prepared_attempt

            def crash_at_authority_unbind(
                store: SQLitePerRunAuthorityStore,
                candidate_run_uri: str,
                *,
                assignment_id: str,
                attempt_id: str,
            ) -> None:
                nonlocal injected
                if candidate_run_uri == run_uri and not injected:
                    injected = True
                    if boundary == "authority_unbound":
                        original_unbind(
                            store,
                            candidate_run_uri,
                            assignment_id=assignment_id,
                            attempt_id=attempt_id,
                        )
                    raise OSError(f"crash at {boundary}")
                original_unbind(
                    store,
                    candidate_run_uri,
                    assignment_id=assignment_id,
                    attempt_id=attempt_id,
                )

            context.setattr(
                SQLitePerRunAuthorityStore,
                "unbind_prepared_attempt",
                crash_at_authority_unbind,
            )
        elif boundary == "logical_released":
            original_advance = execution.slurm_assignments.advance

            def crash_after_logical_release(
                assignment_id: str, *, expected: str, next_state: str
            ) -> str:
                nonlocal injected
                result = original_advance(
                    assignment_id, expected=expected, next_state=next_state
                )
                if (
                    expected == "rejected"
                    and next_state == "logical_released"
                    and not injected
                ):
                    injected = True
                    raise OSError("crash after logical release")
                return result

            context.setattr(
                execution.slurm_assignments, "advance", crash_after_logical_release
            )
        elif boundary == "provider_revoked":
            original_revoke = SlurmJobPrivateFileProvider.revoke

            def crash_after_provider_revoke(
                provider: SlurmJobPrivateFileProvider, capability: object
            ) -> None:
                nonlocal injected
                original_revoke(provider, capability)  # type: ignore[arg-type]
                if not injected:
                    injected = True
                    raise SlurmPlanningError("crash after provider revoke")

            context.setattr(
                SlurmJobPrivateFileProvider, "revoke", crash_after_provider_revoke
            )
        else:
            original_release = execution.slurm_assignments.release

            def crash_after_final_release(assignment_id: str) -> None:
                nonlocal injected
                original_release(assignment_id)
                if not injected:
                    injected = True
                    raise OSError("crash after final release")

            context.setattr(
                execution.slurm_assignments, "release", crash_after_final_release
            )

        client = daemon.client_view(
            LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
        )
        client.submit(LocalDaemonAdmissionRequest("rejected-stage", run_uri))
        try:
            daemon.reconcile_once()
        except OSError as exc:
            assert "crash" in str(exc)

        assert injected
        with sqlite3.connect(config.execution_database) as conn:
            row = conn.execute(
                "SELECT assignment_id, state FROM slurm_stage_assignments"
            ).fetchone()
        assert row is not None
        assignment_id, retained_state = str(row[0]), str(row[1])
        assert retained_state == expected_state
        with sqlite3.connect(_authority_database_path(run_uri)) as conn:
            bindings = int(
                conn.execute(
                    "SELECT COUNT(*) FROM managed_attempt_bindings "
                    "WHERE assignment_id = ?",
                    (assignment_id,),
                ).fetchone()[0]
            )
        assert bool(bindings) is authority_bound
        assert capability_path.exists() is capability_retained

    daemon.stop()
    replacement = LocalDaemon(config)
    replacement.start()
    try:
        replacement_execution = replacement._execution  # noqa: SLF001
        assert replacement_execution is not None
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if (
                replacement_execution.slurm_assignments.read(assignment_id).state
                == "released"
            ):
                break
            time.sleep(0.02)
        assert (
            replacement_execution.slurm_assignments.read(assignment_id).state
            == "released"
        )
        assert not capability_path.exists()
        with sqlite3.connect(_authority_database_path(run_uri)) as conn:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM managed_attempt_bindings "
                    "WHERE assignment_id = ?",
                    (assignment_id,),
                ).fetchone()[0]
                == 0
            )
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM managed_attempt_unbind_receipts "
                    "WHERE assignment_id = ?",
                    (assignment_id,),
                ).fetchone()[0]
                == 1
            )
        with sqlite3.connect(config.execution_database) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM slurm_stage_assignments").fetchone()[
                    0
                ]
                == 1
            )
        assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1
    finally:
        replacement.stop()


@pytest.mark.parametrize("blocked_count", [1, 257])
def test_unavailable_slurm_root_does_not_starve_independent_managed_root(
    tmp_path: Path, blocked_count: int,
) -> None:
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner, available=False)
    run_root = tmp_path / "runs"
    run_store = LocalRunStore(run_root)
    run_uri = path_to_run_uri(run_root / "independent-roots")
    run_store.create_run(run_uri)
    pipeline_config = {
        "name": "independent-roots",
        "stages": [
            {
                "name": "blocked_train",
                "factory": {
                    "_target_": "tests.support.pipeline_execution_stages.JsonProducerStage"
                },
                "config": {"value": 1},
                "outputs": {"data": {"artifact_type": "json", "codec_key": "json.v1"}},
                "placement": {
                    "execution_route": {"kind": "slurm", "profile": "training"}
                },
            },
            {
                "name": "managed_root",
                "factory": {
                    "_target_": "tests.support.pipeline_execution_stages.JsonProducerStage"
                },
                "config": {"value": 2},
                "outputs": {"data": {"artifact_type": "json", "codec_key": "json.v1"}},
            },
        ],
    }
    blocked = pipeline_config["stages"][0]
    pipeline_config["stages"] = [
        {**blocked, "name": f"blocked_train_{index:03d}"} for index in range(blocked_count)
    ] + pipeline_config["stages"][1:]
    pipeline = PipelineSpec.from_config(pipeline_config)
    plan = plan_pipeline(
        pipeline,
        run_uri=run_uri,
        stage_state=run_store,
        artifact_index=run_store,
        plans=run_store,
        artifact_store=LocalArtifactStore(run_store.local_artifact_root(run_uri)),
        persist=True,
    )
    run_store.write_runtime_metadata(
        run_uri,
        {
            "executor": "local",
            "stages": {name: {"executor": "local"} for name in pipeline.stage_names},
        },
    )
    run_store.write_config_snapshot(
        run_uri, "resolved", json_dumps_pretty({"pipeline": pipeline_config})
    )
    prepare_managed_local_runtime_record(
        store=run_store,
        run_uri=run_uri,
        plan=plan,
        pipeline=pipeline,
        execution_requirements=_execution_requirements(pipeline),
        slurm_profiles=(profile,),
    )
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "daemon" / "coordinator",
        agent_root=tmp_path / "daemon" / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=_launch_profile(),
        slurm_profiles=(profile,),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
        )
        client.submit(LocalDaemonAdmissionRequest("independent-roots", run_uri))
        deadline = time.monotonic() + 45
        snapshot = authority.open_run(run_uri)
        while time.monotonic() < deadline:
            snapshot = authority.open_run(run_uri)
            states = {stage.stage_name: stage.status for stage in snapshot.stages}
            if states.get("managed_root") is StageStatus.SUCCEEDED:
                break
            time.sleep(0.02)
        states = {stage.stage_name: stage.status for stage in snapshot.stages}
        assert states == {
            **{f"blocked_train_{index:03d}": StageStatus.PENDING for index in range(blocked_count)},
            "managed_root": StageStatus.SUCCEEDED,
        }
        assert not [call for call in runner.calls if call[0] == "sbatch"]
        assert daemon._execution is not None
        assert not daemon._execution.slurm_assignments.list_run_unreleased(run_uri)
    finally:
        daemon.stop()


@pytest.mark.parametrize(
    ("parallel_limit", "max_outstanding", "expected_submissions"),
    ((2, 1, 1), (2, 2, 2), (2, None, 2),
     (None, 1, 1), (None, 2, 2), (None, None, 2), (None, None, 40)),
)
def test_parallel_slurm_stages_honor_the_profile_outstanding_limit(
    tmp_path: Path,
    parallel_limit: int | None,
    max_outstanding: int | None,
    expected_submissions: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeSlurmCommandRunner(starting_job_id=1300)
    profile = _profile(runner, max_outstanding=max_outstanding)
    # This dispatch test leaves assignments active. Give their separate result
    # reservations enough quota; the small default fixture only fits 15 jobs.
    profile = replace(profile, result_storage={
        **profile.result_storage, "retention_bytes": 8 * 1024 * 1024 * 1024,
    })
    later_limit_decision = Event()
    original_reserve = slurm_ready_stage.SQLiteSlurmStageAssignments.reserve

    def observe_limit(*args: object, **kwargs: object) -> str:
        try:
            return original_reserve(*args, **kwargs)  # type: ignore[arg-type]
        except QueueServiceError as exc:
            if str(exc) == "SLURM profile outstanding limit reached":
                later_limit_decision.set()
            raise

    monkeypatch.setattr(
        slurm_ready_stage.SQLiteSlurmStageAssignments, "reserve", observe_limit
    )
    run_root = tmp_path / "runs"
    run_store = LocalRunStore(run_root)
    run_uri = path_to_run_uri(run_root / "parallel-run")
    run_store.create_run(run_uri)
    pipeline_config = {
        "name": "parallel-slurm",
        "stages": [
            {
                "name": stage_name,
                "factory": {
                    "_target_": "tests.support.pipeline_execution_stages.JsonProducerStage"
                },
                "config": {"value": value},
                "outputs": {"data": {"artifact_type": "json", "codec_key": "json.v1"}},
                "placement": {
                    "execution_route": {"kind": "slurm", "profile": "training"}
                },
            }
            for stage_name, value in (
                (f"stage_{index}", index) for index in range(max(2, expected_submissions))
            )
        ],
    }
    pipeline = PipelineSpec.from_config(pipeline_config)
    plan = plan_pipeline(
        pipeline,
        run_uri=run_uri,
        stage_state=run_store,
        artifact_index=run_store,
        plans=run_store,
        artifact_store=LocalArtifactStore(run_store.local_artifact_root(run_uri)),
        persist=True,
    )
    run_store.write_runtime_metadata(
        run_uri,
        {
            "executor": "local",
            "stages": {name: {"executor": "local"} for name in pipeline.stage_names},
        },
    )
    run_store.write_config_snapshot(
        run_uri,
        "resolved",
        json_dumps_pretty({"pipeline": pipeline_config}),
    )
    prepare_managed_local_runtime_record(
        store=run_store,
        run_uri=run_uri,
        plan=plan,
        pipeline=pipeline,
        execution_requirements=_execution_requirements(pipeline),
        options={"execution": {"settings": {"max_parallel_stages": parallel_limit}}},
        slurm_profiles=(profile,),
    )
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "daemon" / "coordinator",
        agent_root=tmp_path / "daemon" / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=_launch_profile(),
        slurm_profiles=(profile,),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
        )
        client.submit(LocalDaemonAdmissionRequest("parallel-slurm", run_uri))
        execution = daemon._execution
        assert execution is not None
        # The >capacity case persists forty real per-stage sagas, including
        # authority and Slurm journals, on the test filesystem.
        deadline = time.monotonic() + (180 if expected_submissions > 32 else 30)
        while time.monotonic() < deadline:
            submissions = [call for call in runner.calls if call[0] == "sbatch"]
            records = execution.slurm_assignments.list_run_unreleased(run_uri)
            accepted = len(records) == expected_submissions and all(
                record.state == "accepted" for record in records
            )
            if (
                len(submissions) == expected_submissions
                and accepted
                and (expected_submissions != 1 or later_limit_decision.is_set())
            ):
                break
            time.sleep(0.02)
        submissions = [call for call in runner.calls if call[0] == "sbatch"]
        records = execution.slurm_assignments.list_run_unreleased(run_uri)

        assert len(submissions) == expected_submissions
        assert len(records) == expected_submissions
        assert all(record.state == "accepted" for record in records)
        if expected_submissions == len(pipeline.stages):
            assert not execution._ready_preparations._pending
        if expected_submissions == 1:
            assert later_limit_decision.is_set()
        snapshot = authority.open_run(run_uri)
        assert all(stage.status is StageStatus.PENDING for stage in snapshot.stages)
    finally:
        daemon.stop()


@pytest.mark.parametrize("trusted_user", [False, True])
def test_compute_process_exits_during_outage_then_agent_replays_one_commit(
    tmp_path, monkeypatch, trusted_user
):
    _exercise_mixed_route_run(tmp_path, monkeypatch, finish_during_outage=True, trusted_user=trusted_user)


def test_result_from_previous_epoch_survives_long_outage_time_recovery(tmp_path, monkeypatch):
    _exercise_mixed_route_run(
        tmp_path, monkeypatch, finish_during_outage=True,
        trusted_user=True, long_outage=True,
    )


def test_accounting_identity_survives_outage_and_binds_release(tmp_path, monkeypatch):
    _exercise_mixed_route_run(
        tmp_path, monkeypatch, finish_during_outage=True,
        trusted_user=True, long_outage=True, accounting_history=True,
    )


@pytest.mark.parametrize("expired_first_use", [False, True])
def test_trusted_user_registration_enforces_expiry_but_preserves_consumed_replay(
    tmp_path, monkeypatch, expired_first_use,
):
    from datetime import timedelta
    from loom.timestamps import parse_timestamp, utc_timestamp
    from loom.pipeline.executors.slurm.trusted_user import SlurmUserPrivateFileProvider

    runner = FakeSlurmCommandRunner(starting_job_id=1800)
    provider = SlurmUserPrivateFileProvider(root=tmp_path / "credentials", descriptor="trusted-test-v1", ttl_seconds=60)
    profile = replace(_profile(runner), job_private_file_provider=provider)
    run_root = tmp_path / "runs"
    run_uri = _persist_rejected_slurm_run(run_root, profile)
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "daemon" / "coordinator",
        agent_root=tmp_path / "daemon" / "agent",
        run_store_root=run_root, resident_worker_launch_profile=_launch_profile(),
        slurm_profiles=(profile,),
    )
    assert config.slurm_schema_version == 4
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        client = daemon.client_view(LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT))
        client.submit(LocalDaemonAdmissionRequest("expiry-run", run_uri))
        execution = daemon._execution
        assert execution is not None
        deadline = time.monotonic() + 45
        records = ()
        while time.monotonic() < deadline:
            records = execution.slurm_assignments.list_run_unreleased(run_uri)
            if records and records[0].state == "accepted":
                break
            time.sleep(0.02)
        assert len(records) == 1
        record = records[0]
        assert record.state == "accepted", daemon.status()
        assert record.requested_gpu_count == 0
        assert record.capability_delivery_kind == "user_private_file_v1"
        assert record.capability_expires_at is not None
        with sqlite3.connect(config.execution_database) as conn:
            assert conn.execute("PRAGMA user_version").fetchone() == (4,)
        conn.close()
        with sqlite3.connect(config.agent_root / "slurm.sqlite") as conn:
            assert conn.execute("PRAGMA user_version").fetchone() == (3,)
        conn.close()
        view = daemon.slurm_bootstrap_view(LocalDaemonPrincipal("slurm-principal", LocalDaemonRole.SLURM_BOOTSTRAP, "slurm-credential"))
        arguments = dict(
            operation_id=record.assignment.operation_id,
            request_digest=record.assignment.request_digest,
            job_id="1800", cluster="cluster-a", incarnation="bootstrap-1",
            capability=base64.b64encode(provider.read_capability(
                operation_id=record.assignment.operation_id, request_digest=record.assignment.request_digest,
            )).decode(),
        )
        expiry = parse_timestamp(record.capability_expires_at)
        with daemon._cycle_lock:
            before_registration = execution.slurm_assignments.read(record.assignment.assignment_id)
            selected = expiry if expired_first_use else expiry - timedelta(seconds=1)
            monkeypatch.setattr(daemon, "_clock", lambda: utc_timestamp(selected, timespec="microseconds"))
            if expired_first_use:
                with pytest.raises(QueueConflictError, match="first use has expired"):
                    view.register(**arguments)
                assert execution.slurm_assignments.read(record.assignment.assignment_id) == before_registration
            else:
                registration = view.register(**arguments)
                selected = expiry + timedelta(seconds=1)
                assert view.register(**arguments) == registration
                with pytest.raises(QueueConflictError, match="incarnation conflicts"):
                    view.register(**{**arguments, "incarnation": "another-bootstrap"})
            assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1
    finally:
        daemon.stop()


@pytest.mark.parametrize("output_size", [0, 65536, 98304])
def test_agent_recovers_cumulative_output_acknowledgement_before_commit(
    tmp_path, monkeypatch, output_size
):
    _exercise_mixed_route_run(
        tmp_path,
        monkeypatch,
        finish_during_outage=True,
        slurm_output_size=output_size,
        lose_output_ack_at=min(output_size, 65536),
    )


@pytest.mark.optional_dependency
def test_actual_native_preparation_pair_crosses_slurm_ready_helpers_and_ack_replay(
    tmp_path, monkeypatch
):
    """Transport real native bytes through the ready-result interfaces only.

    This bounded protocol fixture supplies an observed ready assignment to the
    storage interface. It does not force dispatcher eligibility or claim native
    preparation execution on Slurm, which has no preparation-input capability.
    """
    from tests.integration.queue.test_preparation_child import _child
    from loom.queue.slurm_ready_stage import (
        SQLiteSlurmStageAssignments,
        SlurmStageAssignment,
    )
    from loom.preparation import load_preparation_report
    from loom.io.uris import uri_to_path

    (tmp_path / "native-source").mkdir()
    _service, _binding, produced, native_workspace, counter = _child(
        tmp_path / "native-source"
    )
    assert counter.read_text() == "1"
    original = produced.outputs["report"]
    logical = load_preparation_report(original, uri_to_path(original.uri))
    runner = FakeSlurmCommandRunner(starting_job_id=1200)
    source_request = native_workspace.worker_request(resolve_shared=True)
    profile = replace(_profile(runner), environment_fingerprint=source_request.metadata["loom.execution_binding"]["environment_fingerprint"])
    assignment = SlurmStageAssignment(
        assignment_id="native-pair",
        operation_id="native-pair-operation",
        run_uri="file:///observed-native-pair",
        stage_work_id="native-pair-work",
        stage_name="prepare",
        attempt=1,
        attempt_id="prepare-1",
        profile_id=profile.profile_id,
        profile_descriptor=profile.descriptor,
        profile_configuration_fingerprint=profile.configuration_fingerprint,
        request_digest="d" * 64,
        agent_id="agent-pair",
        agent_root_id="root-pair",
    )
    from loom.pipeline.resources import ResourceRequest
    from loom.pipeline.stores.input_lineage import binding_evidence

    source_request = native_workspace.worker_request(resolve_shared=True)
    assert source_request.inputs == {}
    assert source_request.metadata["attempt_input_evidence"] == binding_evidence(())
    # Localized transport retains a digest; a new delivery requires the original
    # authority bindings. This fixture's native preparation has zero inputs.
    transport_request = replace(
        source_request,
        run_uri=assignment.run_uri,
        resolved_runtime={
            **source_request.resolved_runtime,
            "resources": ResourceRequest().to_dict(),
        },
        metadata={**source_request.metadata, "attempt_input_bindings": []},
    )
    for missing in ("absent", "null"):
        metadata = dict(transport_request.metadata)
        if missing == "absent":
            del metadata["attempt_input_bindings"]
        else:
            metadata["attempt_input_bindings"] = None
        with pytest.raises(ValueError, match="requires retained input bindings"):
            SlurmStageDelivery.from_worker_request(
                assignment=assignment,
                worker_request=replace(transport_request, metadata=metadata),
                project_fingerprint=profile.project_fingerprint,
                environment_fingerprint=profile.environment_fingerprint,
                executor_fingerprint=profile.executor_fingerprint,
                inputs=(),
                declared_outputs=("report",),
            )
    delivery = SlurmStageDelivery.from_worker_request(
        assignment=assignment,
        worker_request=transport_request,
        project_fingerprint=profile.project_fingerprint,
        environment_fingerprint=profile.environment_fingerprint,
        executor_fingerprint=profile.executor_fingerprint,
        inputs=(),
        declared_outputs=("report",),
    )
    workspace = SlurmBootstrapWorkspace(tmp_path / "compute", assignment.assignment_id)
    workspace.persist_delivery(delivery)
    # Relocation is a transport fixture, not new native execution authority.
    primary = uri_to_path(original.uri)
    artifact_root = workspace.root / "artifacts/prepare"
    artifact_root.mkdir(parents=True)
    for path in primary.parent.iterdir():
        if path.is_file():
            shutil.copyfile(path, artifact_root / path.name)
    relocated = replace(original, uri=(artifact_root / primary.name).as_uri())
    result = replace(
        produced,
        run_uri=f"loom-slurm:{assignment.assignment_id}",
        outputs={"report": relocated},
    )
    report = workspace.retain_result(result)
    assert report.schema_version == 6
    assert report.output_kind == "preparation_report"
    assert (
        len(report.outputs) == 1
        and report.outputs[0].preparation_report_transfer is not None
    )
    owner = SQLiteSlurmStageAssignments(tmp_path / "ready.sqlite", tmp_path / "relay")
    owner._initialize()
    # Populate the supported storage-interface observation, including all its
    # original assignment/delivery/fence identities. No scheduler is bypassed.
    with sqlite3.connect(owner.path) as conn:
        conn.execute(
            "INSERT INTO slurm_stage_assignments (assignment_id,operation_id,run_uri,stage_work_id,profile_id,state,identity_json,request_json,delivery_json,input_paths_json,issuer_epoch,job_id,cluster,bootstrap_incarnation,input_ready,fence,process_execution_id,report_json,capability_verifier,submission_eligible,capability_consumed) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                assignment.assignment_id,
                assignment.operation_id,
                assignment.run_uri,
                assignment.stage_work_id,
                assignment.profile_id,
                "running",
                json.dumps(assignment.to_dict()),
                json.dumps({"digest": assignment.request_digest}),
                json.dumps(delivery.to_dict()),
                "{}",
                "epoch-pair",
                "1200",
                "cluster-a",
                "bootstrap-pair",
                1,
                "fence-pair",
                "worker-pair",
                None,
                "e" * 64,
                1,
                1,
            ),
        )
    downgraded = replace(
        report, output_kind="relay",
        outputs=tuple(replace(item, preparation_report_transfer=None) for item in report.outputs),
    )
    with pytest.raises(QueueConflictError, match="native preparation transfer capability"):
        owner.declare_report(assignment.assignment_id, "bootstrap-pair", "fence-pair", downgraded)
    owner.declare_report(
        assignment.assignment_id, "bootstrap-pair", "fence-pair", report
    )
    item = report.outputs[0]
    with pytest.raises(QueueConflictError, match="coordinator-accessible"):
        owner.committed_result(assignment.assignment_id, "bootstrap-pair", "fence-pair")
    offset = 0
    original_publish = slurm_ready_stage._publish_staged_file
    crashed = False
    while True:
        chunk, final = workspace.output_chunk(item.transfer_id, offset)
        if final and not crashed:
            crashed = True

            def after_publish(part, target):
                original_publish(part, target)
                raise OSError("native pair lost acknowledgement")

            monkeypatch.setattr(
                slurm_ready_stage, "_publish_staged_file", after_publish
            )
            with pytest.raises(OSError, match="lost acknowledgement"):
                owner.write_output_chunk(
                    assignment.assignment_id,
                    "bootstrap-pair",
                    item.transfer_id,
                    offset,
                    chunk,
                    final=final,
                )
            monkeypatch.setattr(
                slurm_ready_stage, "_publish_staged_file", original_publish
            )
            with pytest.raises(QueueConflictError, match="coordinator-accessible"):
                owner.committed_result(
                    assignment.assignment_id, "bootstrap-pair", "fence-pair"
                )
        offset = owner.write_output_chunk(
            assignment.assignment_id,
            "bootstrap-pair",
            item.transfer_id,
            offset,
            chunk,
            final=final,
        )
        if final:
            break
    received, outputs = owner.committed_result(
        assignment.assignment_id, "bootstrap-pair", "fence-pair"
    )
    assert received == report
    restored = outputs["report"]
    assert replace(original, uri=restored.uri) == restored
    assert load_preparation_report(restored, uri_to_path(restored.uri)) == logical
    assert "preparation_report_transfer" not in restored.metadata
    replay = SlurmBootstrapWorkspace(tmp_path / "compute", assignment.assignment_id)
    assert replay.retained_report() == report
    assert workspace.retain_result(result) == report
    owner.declare_report(
        assignment.assignment_id, "bootstrap-pair", "fence-pair", report
    )
    offset = 0
    while True:
        chunk, final = replay.output_chunk(item.transfer_id, offset)
        offset = owner.write_output_chunk(
            assignment.assignment_id,
            "bootstrap-pair",
            item.transfer_id,
            offset,
            chunk,
            final=final,
        )
        if final:
            break
    assert owner.committed_result(
        assignment.assignment_id, "bootstrap-pair", "fence-pair"
    ) == (report, outputs)
    with pytest.raises(QueueConflictError, match="authorization"):
        owner.committed_result(
            assignment.assignment_id, "bootstrap-other", "fence-pair"
        )
    assert counter.read_text() == "1"


def test_slow_shared_publication_allows_unrelated_gpu_dispatch_and_cancellation(
    tmp_path, monkeypatch,
):
    from types import SimpleNamespace
    from loom.pipeline.resources import ResourceEntry, ResourceRequest
    from loom.queue.agent_sessions import AgentSessionService
    from loom.queue.local_daemon_execution import _SlurmPublicationRequired
    from loom.queue import _shared_publication as publication
    from loom.queue._slurm_admission import SlurmAdmissionPolicy
    from tests.unit.loom.queue.test_slurm_ready_stage import _shared_slurm_workspace

    (tmp_path / "publication").mkdir()
    workspace, shared_profile, result = _shared_slurm_workspace(tmp_path / "publication")
    record = SimpleNamespace(
        assignment=SimpleNamespace(agent_id="agent-1", assignment_id=workspace.root.name),
        delivery=workspace.delivery(), report=workspace.retain_result(result),
        bootstrap_incarnation="bootstrap", fence="fence-1",
    )
    runner = FakeSlurmCommandRunner()
    profile = _profile(runner)
    run_root = tmp_path / "runs"
    run_uri = _persist_rejected_slurm_run(run_root, profile, resources=ResourceRequest(entries={
        "cpu": ResourceEntry("cpu", 1, "count"),
        "gpu": ResourceEntry("gpu", 1, "count", {"allocation_mode": "exclusive"}),
    }))
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=_launch_profile(),
        slurm_profiles=(profile,),
        shared_roots=shared_profile.shared_roots,
        slurm_admission=SlurmAdmissionPolicy(8),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    execution = daemon._execution
    assert execution is not None
    entered, proceed = Event(), Event()
    original_prepare = publication.prepare_publication

    def slow_prepare(*args, **kwargs):
        entered.set()
        assert proceed.wait(15), "test did not release publication IO"
        return original_prepare(*args, **kwargs)

    monkeypatch.setattr(publication, "prepare_publication", slow_prepare)

    # Supply an already validated publication fixture at the authority boundary.
    # Exercise the real lock/continuation and filesystem owners; unrelated work
    # goes through the real daemon client, scheduler and Slurm assignment store.
    def locked(session, epoch, evidence, cursor, **options):
        if options.get("_defer_publication"):
            raise _SlurmPublicationRequired(execution, record, "fence-1")
        token = options["_publication"]
        assert token.validates(execution, record, "fence-1")
        return publication.accept_publication(token.prepared)

    service = SimpleNamespace(_daemon=daemon, _slurm_work_locked=locked)
    evidence = {"result_operation": "commit", "assignment_id": workspace.root.name}
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            sealing = workers.submit(AgentSessionService.slurm_work, service, "session", "epoch", evidence)
            try:
                assert entered.wait(5)
                client = daemon.client_view(LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT))
                workers.submit(client.submit, LocalDaemonAdmissionRequest("independent", run_uri)).result(timeout=5)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    records = execution.slurm_assignments.list_run_unreleased(run_uri)
                    if records and records[0].state == "accepted":
                        break
                    time.sleep(0.02)
                assert len(records) == 1 and records[0].state == "accepted"
                assert records[0].requested_gpu_count == 1
                assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1
                cancelled = workers.submit(client.cancel, "independent").result(timeout=5)
                assert cancelled.cancellation_operation_id is not None
                assert not sealing.done(), "publication must still be waiting during dispatch/cancellation"
            finally:
                proceed.set()
            assert sealing.result(timeout=5)
    finally:
        proceed.set()
        daemon.stop()


def test_gpu_budget_survives_restart_and_reload_preserves_admitted_work(tmp_path):
    from loom.pipeline.resources import ResourceEntry, ResourceRequest
    from loom.pipeline.executors.slurm.trusted_user import SlurmUserPrivateFileProvider
    from loom.queue import CoordinatorSchedulingReload
    from loom.pipeline.planning import PlanAction
    from loom.queue.local_daemon_execution import load_managed_local_intent
    from loom.queue.deployment import load_coordinator_service_config
    from tests.unit.loom.queue.test_deployment import _coordinator_config, _write_protected

    def resources(quantity):
        return ResourceRequest(entries={
            "cpu": ResourceEntry("cpu", 1, "count"),
            **({"gpu": ResourceEntry("gpu", quantity, "count", {"allocation_mode": "exclusive"})}
               if quantity else {}),
        })

    runner = FakeSlurmCommandRunner()
    profile = replace(
        _profile(runner), max_outstanding=None,
        job_private_file_provider=SlurmUserPrivateFileProvider(
            root=tmp_path / "credentials", descriptor="trusted-budget-test",
        ),
    )
    source = _coordinator_config(tmp_path)
    payload = json.loads(source.read_text())
    payload["slurm_admission"] = {"max_reserved_gpus": 8}
    payload["agent_policy"]["principals"] = [{
        "credential_id": "operator-certificate", "principal_id": "operator",
        "role": "operator", "actions": ["scheduling_reload"], "agent_ids": [], "pools": [],
    }]
    payload["slurm_profiles"] = [{
        key: getattr(profile, key) for key in (
            "profile_id", "partition", "max_outstanding", "command_adapter_fingerprint",
            "bootstrap_principal_id", "credential_reference", "coordinator_endpoint",
            "project_fingerprint", "environment_fingerprint", "executor_fingerprint", "cluster",
        )
    }]
    payload["slurm_profiles"][0].update(
        runner={"_target_": "loom.pipeline.executors.slurm.FakeSlurmCommandRunner"},
        result_storage=dict(profile.result_storage),
        job_private_file_provider={
            "_target_": "loom.pipeline.executors.slurm.trusted_user.SlurmUserPrivateFileProvider",
            "root": str(tmp_path / "credentials"), "descriptor": "trusted-budget-test",
        },
    )
    _write_protected(source, payload)
    service = load_coordinator_service_config(source)
    config = service.daemon
    profile = config.slurm_profiles[0]
    runner = profile.runner
    runs = {
        key: _persist_rejected_slurm_run(config.run_store_root / key, profile, resources=resources(quantity))
        for key, quantity in (("cpu-early", 0), ("left", 4), ("right", 4), ("waiting", 1), ("cpu", 0), ("oversize", 9))
    }
    replacement = config
    LocalDaemon.initialize_deployment(config)
    daemon = LocalDaemon(config, trusted_scheduling_loader=lambda: replacement)
    daemon.start()

    def until(predicate):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.02)
        pytest.fail("coordinator did not reach the expected admission outcome")

    def accepted(key):
        records = daemon._execution.slurm_assignments.list_run_unreleased(runs[key])
        return len(records) == 1 and records[0].state == "accepted"

    def reload_budget(budget, operation):
        nonlocal replacement, service
        payload["slurm_admission"] = {"max_reserved_gpus": budget}
        _write_protected(source, payload)
        candidate = load_coordinator_service_config(source, current=service)
        replacement = candidate.daemon
        assert replacement.slurm_profiles[0] is service.daemon.slurm_profiles[0]
        operator = daemon.operator_view(LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR))
        receipt = operator.reload_scheduling(CoordinatorSchedulingReload(
            operation_id=operation, expected_scheduling_epoch=daemon.status().scheduling_epoch,
            reason="test GPU budget reload",
        ))
        if receipt["state"] == "applied":
            service = candidate
        return receipt

    try:
        client = daemon.client_view(LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT))
        # A retained CPU assignment from another experiment must not block GPU
        # admission. Keep it active throughout GPU saturation and restart.
        client.submit(LocalDaemonAdmissionRequest("cpu-early", runs["cpu-early"]))
        until(lambda: accepted("cpu-early"))
        for key in ("left", "right"):
            client.submit(LocalDaemonAdmissionRequest(key, runs[key]))
            until(lambda: accepted(key))
        assert accepted("cpu-early")
        assert daemon._execution.slurm_assignments.reserved_gpu_count() == 8
        oversized = load_managed_local_intent(config, runs["oversize"])
        for action in (PlanAction.SKIP, PlanAction.REUSE):
            # Admission checks resources only for stages the planner will run.
            plan = replace(oversized.plan, stage_plans=tuple(
                replace(stage, action=action, base_action=action)
                for stage in oversized.plan.stage_plans
            ))
            daemon._execution.validate_fresh_intent(replace(oversized, plan=plan))
        with pytest.raises(QueueConflictError, match="exceeds GPU reservation budget"):
            client.submit(LocalDaemonAdmissionRequest("oversize", runs["oversize"]))
        client.submit(LocalDaemonAdmissionRequest("waiting", runs["waiting"]))
        until(lambda: client.admission_for_queue_item("waiting").blocked_reason == "slurm_gpu_capacity_reserved")
        client.submit(LocalDaemonAdmissionRequest("cpu", runs["cpu"]))
        until(lambda: accepted("cpu"))
        assert daemon._execution.slurm_assignments.reserved_gpu_count() == 8
        assert not daemon._execution.slurm_assignments.list_run_unreleased(runs["waiting"])
        before = {
            key: daemon._execution.slurm_assignments.list_run_unreleased(runs[key])[0]
            for key in ("cpu-early", "left", "right", "cpu")
        }
        assert reload_budget(7, "lower-too-far")["code"] == "reload_rejected"
        assert daemon.config is config
        assert len([call for call in runner.calls if call[0] == "sbatch"]) == 4
        daemon.stop()
        payload["slurm_admission"] = {"max_reserved_gpus": 8}
        _write_protected(source, payload)
        replacement = config
        daemon = LocalDaemon(config, trusted_scheduling_loader=lambda: replacement)
        daemon.start()
        client = daemon.client_view(LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT))
        assert daemon._execution.slurm_assignments.reserved_gpu_count() == 8
        for key, previous in before.items():
            current = daemon._execution.slurm_assignments.list_run_unreleased(runs[key])[0]
            assert current.assignment == previous.assignment
            assert current.job_id == previous.job_id
        assert len([call for call in runner.calls if call[0] == "sbatch"]) == 4
        assert reload_budget(9, "increase")["state"] == "applied"
        until(lambda: accepted("waiting"))
        assert daemon._execution.slurm_assignments.reserved_gpu_count() == 9
        assert len([call for call in runner.calls if call[0] == "sbatch"]) == 5
        assert client.admission_for_queue_item("waiting").state is LocalDaemonAdmissionState.ACTIVE
        assert reload_budget(None, "disable")["state"] == "applied"
        assert daemon.config.slurm_schema_version == 4
        assert daemon._execution.slurm_assignments.reserved_gpu_count() == 9
        assert len([call for call in runner.calls if call[0] == "sbatch"]) == 5
    finally:
        daemon.stop()


def test_consumed_grant_without_started_recovers_and_releases_after_restart(tmp_path, monkeypatch):
    _exercise_mixed_route_run(
        tmp_path, monkeypatch, guarded_recovery=True, prestart_failure=True,
        accounting_history=True, recovery_terminal_state="FAILED",
    )


def test_replayable_start_survives_coordinator_restart_and_prestart_recovery(tmp_path, monkeypatch):
    _exercise_mixed_route_run(
        tmp_path, monkeypatch, guarded_recovery=True, prestart_failure=True,
        accounting_history=True, recovery_terminal_state="FAILED", replayable_start=True,
    )
