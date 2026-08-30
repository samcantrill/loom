"""Explicit ready-stage SLURM production-path integration coverage."""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import base64
import sqlite3
import sys
import time
from threading import Event
from typing import cast

import pytest

import loom.queue.slurm_ready_stage as slurm_ready_stage
from loom.pipeline import PipelineSpec
from loom.pipeline.execution.stage_worker import execute_resident_stage_worker_request
from loom.pipeline.executors.slurm.commands import (
    FakeSlurmCommandRunner,
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
    prepare_managed_local_runtime_record,
)
from loom.queue.agent_sessions import AgentPolicyConfig, TransportPrincipalPolicy
from loom.queue.errors import QueueConflictError, QueueServiceError
from loom.queue._remote_stage_execution import ResidentProfileDescriptor
from loom.queue.slurm_ready_stage import SlurmBootstrapWorkspace, SlurmStageDelivery
from loom.serialization import json_dumps_pretty


pytestmark = pytest.mark.integration


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
    max_outstanding: int = 1,
    available: bool = True,
    containment_helper: SlurmContainmentHelper | None = None,
    capability_path: Path | None = None,
) -> SlurmReadyStageProfile:
    return SlurmReadyStageProfile(
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
            fixed_path=str(capability_path or "/tmp/loom-integration-capability"),
            descriptor="fake-prolog-v1",
            helper_argv=_TEST_HELPER,
        ),
        cluster="cluster-a",
        available=available,
        containment_helper=containment_helper,
    )


def _positive_containment_helper() -> SlurmContainmentHelper:
    program = (
        "import json,sys; value=json.load(sys.stdin); "
        "print(json.dumps({'state':'CONTAINED','evidence_id':'proof-1',"
        "'evidence_revision':'1','echo':value}))"
    )
    return SlurmContainmentHelper("test-contained-v1", (sys.executable, "-c", program))


def _persist_rejected_slurm_run(run_root: Path, profile: SlurmReadyStageProfile) -> str:
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
    pipeline = PipelineSpec.from_config(pipeline_config)
    plan = plan_pipeline(
        pipeline,
        run_uri=run_uri,
        run_store=run_store,
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


def test_slurm_containment_requires_exact_positive_echo() -> None:
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
            "test-contained-v1", (sys.executable, "-c", echo_program)
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
            "test-contained-v1", (sys.executable, "-c", mismatch_program)
        ),
    )
    assert not resolve_slurm_containment(profile, request).contained


def test_slurm_containment_timeout_is_part_of_retained_profile_identity() -> None:
    runner = FakeSlurmCommandRunner()
    helper = SlurmContainmentHelper("site-helper-v1", ("site-helper",), 5.0)
    slower = replace(helper, timeout_seconds=10.0)

    first = replace(_profile(runner), containment_helper=helper)
    second = replace(_profile(runner), containment_helper=slower)

    assert first.configuration_fingerprint != second.configuration_fingerprint


def _exercise_mixed_route_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    terminal_boundary: str | None = None,
    *,
    guarded_recovery: bool = False,
) -> None:
    runner = FakeSlurmCommandRunner(starting_job_id=1200)
    containment_helper = _positive_containment_helper() if guarded_recovery else None
    profile = _profile(runner, containment_helper=containment_helper)
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
                    "_target_": "tests.support.pipeline_execution_stages.TextConsumerStage"
                },
                "depends_on": ["preprocess"],
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
        run_store=run_store,
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
                actions=("recover_unknown",),
            ),
        )
    )
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "daemon" / "coordinator",
        agent_root=tmp_path / "daemon" / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=_launch_profile(),
        agent_policy=agent_policy,
        slurm_profiles=(profile,),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
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
                    Path(profile.job_private_file_provider.fixed_path).read_bytes()
                ).decode(),
            )
            return original_sbatch(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(runner, "sbatch", register_inside_sbatch)
        client = daemon.client_view(
            LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
        )
        client.submit(LocalDaemonAdmissionRequest("mixed-route", run_uri))
        execution = daemon._execution
        assert execution is not None
        deadline = time.monotonic() + 10
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
        assert waited_operation.operation == operation

        # A fresh daemon/execution/store and fresh helper binding retain the
        # accepted operation rather than preparing or submitting it again.
        daemon.stop()
        fresh_runner = FakeSlurmCommandRunner(
            scripted_results={"sbatch": [AssertionError("must not submit")]}
        )
        profile = _profile(fresh_runner, containment_helper=containment_helper)
        reopened_config = LocalDaemonConfig(
            coordinator_root=tmp_path / "daemon" / "coordinator",
            agent_root=tmp_path / "daemon" / "agent",
            run_store_root=run_root,
            resident_worker_launch_profile=_launch_profile(),
            agent_policy=agent_policy,
            slurm_profiles=(profile,),
        )
        daemon = LocalDaemon(reopened_config)
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
                Path(profile.job_private_file_provider.fixed_path).read_bytes()
            ).decode(),
        )
        capability = base64.b64encode(
            Path(profile.job_private_file_provider.fixed_path).read_bytes()
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
        workspace = SlurmBootstrapWorkspace(tmp_path / "compute", assignment_id)
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
        view.inputs_ready(assignment_id, incarnation)
        fence = view.grant(assignment_id, incarnation)
        assert view.start_permit(assignment_id, incarnation, fence) is True
        assert view.start_permit(assignment_id, incarnation, fence) is False
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
                process_execution_id="slurm-root-process-1",
                execution_fence=fence,
                target=SlurmRecoveryTarget(
                    profile.profile_id,
                    record.assignment.operation_id,
                    "cluster-a",
                    "1200",
                    incarnation,
                ),
                expected_state_version=attempt.revision.sequence,
                requested_outcome="cancelled",
                consider_retry=True,
                reason="SLURM containment integration proof",
            )
            operator = daemon.operator_view(
                LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
            )
            execution.slurm_submissions._record_observation(  # noqa: SLF001
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
                    conn.execute("SELECT COUNT(*) FROM recovery_operations").fetchone()[
                        0
                    ]
                    == 0
                )
            assert not daemon._recovery_fences_ordinary_terminal(  # noqa: SLF001
                assignment_id
            )

            unknown_observation = execution.slurm_submissions._record_observation(  # noqa: SLF001
                record.assignment.operation_id,
                expected_job_id="1200",
                scheduler_state=None,
                scheduler_source="unavailable",
                observed_at="2030-01-01T00:00:01+00:00",
            )
            assert unknown_observation.scheduler_source == "unavailable"
            assert unknown_observation.scheduler_state is None
            recovery_receipt = operator.recover_unknown(recovery_request)
            assert recovery_receipt["state"] == "closed"
            assert recovery_receipt["retry_allowed"] is False
            assert recovery_receipt["physical_ownership"] == "retained"
            recovery_evidence = cast(dict[str, object], recovery_receipt["evidence"])
            assert recovery_evidence["kind"] == "slurm_helper"
            assert recovery_evidence["helper_descriptor"] == "test-contained-v1"
            assert authority.open_run(run_uri).stages[1].status is StageStatus.CANCELLED
        worker_result = execute_resident_stage_worker_request(
            worker_request=workspace.worker_request(),
            workspace_root=workspace.root,
        )
        report = workspace.retain_result(worker_result)
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
        if guarded_recovery:
            assert recovery_receipt is not None
            with pytest.raises(QueueConflictError, match="frozen by guarded recovery"):
                view.commit_result(assignment_id, incarnation, fence)
            retained_after_close = execution.slurm_assignments.read(assignment_id)
            assert retained_after_close.state != "released"
            assert execution.slurm_assignments.list_run_unreleased(run_uri) == (
                retained_after_close,
            )
            assert Path(profile.job_private_file_provider.fixed_path).exists()
            assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1
            return
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
            script = (
                config.slurm_script_root / f"{record.assignment.assignment_id}.sh"
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
        original_revoke = SlurmJobPrivateFileProvider.revoke

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
            SlurmJobPrivateFileProvider, "revoke", revoke_with_lost_response
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

        deadline = time.monotonic() + 2
        while (
            execution.slurm_assignments.read(assignment_id).state != "released"
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        assert revoke_calls >= 2, daemon.status()
        assert execution.slurm_assignments.read(assignment_id).state == "released"
        assert not Path(profile.job_private_file_provider.fixed_path).exists()
        assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1
    finally:
        daemon.stop()


def test_mixed_route_run_uses_one_slurm_submit_and_verified_loom_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _exercise_mixed_route_run(tmp_path, monkeypatch)


def test_slurm_guarded_recovery_closes_from_exact_helper_and_retains_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _exercise_mixed_route_run(tmp_path, monkeypatch, guarded_recovery=True)


@pytest.mark.parametrize(
    "terminal_boundary",
    ["authority_result", "assignment_terminal"],
)
def test_terminal_slurm_result_reconciliation_releases_after_crash_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, terminal_boundary: str
) -> None:
    _exercise_mixed_route_run(tmp_path, monkeypatch, terminal_boundary)


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


def test_unavailable_slurm_root_does_not_starve_independent_managed_root(
    tmp_path: Path,
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
    pipeline = PipelineSpec.from_config(pipeline_config)
    plan = plan_pipeline(
        pipeline,
        run_uri=run_uri,
        run_store=run_store,
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
        deadline = time.monotonic() + 10
        snapshot = authority.open_run(run_uri)
        while time.monotonic() < deadline:
            snapshot = authority.open_run(run_uri)
            states = {stage.stage_name: stage.status for stage in snapshot.stages}
            if states.get("managed_root") is StageStatus.SUCCEEDED:
                break
            time.sleep(0.02)
        states = {stage.stage_name: stage.status for stage in snapshot.stages}
        assert states == {
            "blocked_train": StageStatus.PENDING,
            "managed_root": StageStatus.SUCCEEDED,
        }
        assert not [call for call in runner.calls if call[0] == "sbatch"]
        assert daemon._execution is not None
        assert not daemon._execution.slurm_assignments.list_run_unreleased(run_uri)
    finally:
        daemon.stop()


@pytest.mark.parametrize(
    ("max_outstanding", "expected_submissions"),
    ((1, 1), (2, 2)),
)
def test_parallel_slurm_stages_honor_the_profile_outstanding_limit(
    tmp_path: Path,
    max_outstanding: int,
    expected_submissions: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeSlurmCommandRunner(starting_job_id=1300)
    profile = _profile(runner, max_outstanding=max_outstanding)
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
            for stage_name, value in (("left", 1), ("right", 2))
        ],
    }
    pipeline = PipelineSpec.from_config(pipeline_config)
    plan = plan_pipeline(
        pipeline,
        run_uri=run_uri,
        run_store=run_store,
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
        options={"execution": {"settings": {"max_parallel_stages": 2}}},
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
        deadline = time.monotonic() + 5
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
        if expected_submissions == 1:
            assert later_limit_decision.is_set()
        snapshot = authority.open_run(run_uri)
        assert all(stage.status is StageStatus.PENDING for stage in snapshot.stages)
    finally:
        daemon.stop()
