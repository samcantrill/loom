"""Explicit ready-stage SLURM production-path integration coverage."""

from __future__ import annotations

from pathlib import Path
import time
from typing import cast

import pytest

import loom.queue.slurm_ready_stage as slurm_ready_stage
from loom.pipeline import PipelineSpec
from loom.pipeline.execution.stage_worker import execute_resident_stage_worker_request
from loom.pipeline.executors.slurm.commands import FakeSlurmCommandRunner
from loom.pipeline.executors.slurm.ready_stage import (
    SQLiteReadyStageSubmissions,
    SlurmReadyStageProfile,
)
from loom.pipeline.planning import plan_pipeline
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore, path_to_run_uri
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.queue import (
    LocalDaemon,
    LocalDaemonAdmissionRequest,
    LocalDaemonAdmissionState,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    prepare_managed_local_runtime_record,
)
from loom.queue.errors import QueueConflictError
from loom.queue.slurm_ready_stage import SlurmBootstrapWorkspace, SlurmStageDelivery
from loom.serialization import json_dumps_pretty


pytestmark = pytest.mark.integration


def _profile(
    runner: FakeSlurmCommandRunner, *, max_outstanding: int = 1
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
        cluster="cluster-a",
    )


def test_mixed_route_run_uses_one_slurm_submit_and_verified_loom_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeSlurmCommandRunner(starting_job_id=1200)
    profile = _profile(runner)
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
        slurm_profiles=(profile,),
    )
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "daemon" / "coordinator",
        agent_root=tmp_path / "daemon" / "agent",
        run_store_root=run_root,
        slurm_profiles=(profile,),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
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
            )

        view = daemon.slurm_bootstrap_view(
            LocalDaemonPrincipal(
                "slurm-principal",
                LocalDaemonRole.SLURM_BOOTSTRAP,
                "slurm-credential",
            )
        )
        incarnation = "bootstrap-1"
        registration = view.register(
            operation_id=record.assignment.operation_id,
            request_digest=record.assignment.request_digest,
            job_id="1200",
            cluster="cluster-a",
            incarnation=incarnation,
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
) -> None:
    runner = FakeSlurmCommandRunner(starting_job_id=1300)
    profile = _profile(runner, max_outstanding=max_outstanding)
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
        options={"execution": {"settings": {"max_parallel_stages": 2}}},
        slurm_profiles=(profile,),
    )
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "daemon" / "coordinator",
        agent_root=tmp_path / "daemon" / "agent",
        run_store_root=run_root,
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
            if len(submissions) >= expected_submissions:
                break
            time.sleep(0.02)
        if expected_submissions == 1:
            time.sleep(0.2)
        submissions = [call for call in runner.calls if call[0] == "sbatch"]
        records = execution.slurm_assignments.list_run_unreleased(run_uri)

        assert len(submissions) == expected_submissions
        assert len(records) == expected_submissions
        assert all(record.state == "accepted" for record in records)
        snapshot = authority.open_run(run_uri)
        assert all(stage.status is StageStatus.PENDING for stage in snapshot.stages)
    finally:
        daemon.stop()
