"""Run fake-SLURM rejection, restart, result, and release through Loom."""

from __future__ import annotations

import base64
from collections.abc import Mapping
import os
from pathlib import Path
import sys


OPERATIONS_ROOT = Path(__file__).resolve().parents[1]
if str(OPERATIONS_ROOT) not in sys.path:
    sys.path.insert(0, str(OPERATIONS_ROOT))

from _managed_journey_support import (  # noqa: E402
    JourneyRecorder,
    assert_processes_dead,
    example_root,
    wait_until,
)
from loom.artifacts import ArtifactRef  # noqa: E402
from loom.pipeline import PipelineSpec  # noqa: E402
from loom.pipeline.context import StageContext  # noqa: E402
from loom.pipeline.execution.stage_worker import (  # noqa: E402
    execute_resident_stage_worker_request,
)
from loom.pipeline.executors.slurm.commands import (  # noqa: E402
    FakeSlurmCommandRunner,
    SlurmCommandResult,
)
from loom.pipeline.executors.slurm.ready_stage import (  # noqa: E402
    SlurmJobPrivateFileProvider,
    SlurmReadyStageProfile,
)
from loom.pipeline.planning import plan_pipeline  # noqa: E402
from loom.pipeline.stores import (  # noqa: E402
    LocalArtifactStore,
    LocalRunStore,
    path_to_run_uri,
)
from loom.pipeline.stores.coordinator_authority import (  # noqa: E402
    initialize_embedded_coordinator_authority,
)
from loom.queue import (  # noqa: E402
    ExecutionRequirement,
    LocalDaemon,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    LocalDaemonSocketServer,
    ResidentWorkerLaunchProfile,
    prepare_managed_local_runtime_record,
)
from loom.queue.slurm_ready_stage import (  # noqa: E402
    SlurmBootstrapWorkspace,
    SlurmStageDelivery,
)
from loom.serialization import json_dumps_pretty  # noqa: E402


class ProduceStage:
    def run(
        self, context: StageContext, inputs: Mapping[str, ArtifactRef]
    ) -> Mapping[str, ArtifactRef]:
        del inputs
        return {
            "data": context.save_artifact(
                "data", {"value": 42}, artifact_type="json", codec_key="json.v1"
            )
        }


def main() -> None:
    recorder = JourneyRecorder()
    root = example_root("managed-ready-stage-slurm")
    capability_path = root / "job-private-capability"
    runner = FakeSlurmCommandRunner(
        starting_job_id=1800,
        scripted_results={"sbatch": [SlurmCommandResult("sbatch", ("sbatch",), 1)]},
    )
    profile = SlurmReadyStageProfile(
        profile_id="training",
        partition="gpu",
        max_outstanding=1,
        bootstrap_argv=("loom", "slurm-bootstrap"),
        runner=runner,
        command_adapter_fingerprint="fake-slurm-v1",
        bootstrap_principal_id="slurm-principal",
        credential_reference="slurm-credential",
        coordinator_endpoint="https://coordinator.example",
        project_fingerprint="example-project",
        environment_fingerprint="example-environment",
        executor_fingerprint="example-executor",
        job_private_file_provider=SlurmJobPrivateFileProvider(
            fixed_path=str(capability_path),
            descriptor="example-job-private-file-v1",
            helper_argv=(
                sys.executable,
                str(Path(__file__).with_name("job_private_file_helper.py")),
            ),
        ),
        cluster="example-cluster",
    )
    run_root = root / "runs"
    rejected_uri = _prepare_run(recorder, run_root, "rejected", profile)
    completed_uri = _prepare_run(recorder, run_root, "completed", profile)
    config = LocalDaemonConfig(
        coordinator_root=root / "coordinator",
        agent_root=root / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=ResidentWorkerLaunchProfile(
            project_root=Path(__file__).resolve().parent,
            python_executable=Path(sys.executable),
            descriptor={
                "profile_id": "local-default",
                "revision": "v1",
                "project_fingerprint": "example-project",
                "environment_fingerprint": "example-environment",
                "executor_fingerprint": "example-executor",
            },
        ),
        slurm_profiles=(profile,),
    )
    recorder.python("LocalDaemon.initialize", lambda: LocalDaemon.initialize(config))

    first = LocalDaemon(config)
    first_server = LocalDaemonSocketServer(first, config.endpoint)
    try:
        recorder.python("LocalDaemon.start", first.start)
        recorder.python("LocalDaemonSocketServer.start", first_server.start)
        recorder.observe_process_tree(os.getpid())
        recorder.cli("queue", "daemon-status", "--endpoint", str(config.endpoint))
        rejected = recorder.cli(
            "queue",
            "daemon-submit",
            "--endpoint",
            str(config.endpoint),
            "rejected-stage",
            rejected_uri,
        )
        rejected_assignment = wait_until(
            lambda: _slurm_assignment(recorder, config.endpoint, rejected, "released"),
            timeout=15,
        )
        rejected_operation_id = str(rejected_assignment["operation_id"])
        rejected_operation = recorder.cli(
            "queue",
            "daemon-operation-wait",
            "--endpoint",
            str(config.endpoint),
            rejected_operation_id,
            "--timeout",
            "15",
        )
        rejected_operation_detail = rejected_operation.get("operation")
        if (
            not isinstance(rejected_operation_detail, Mapping)
            or rejected_operation_detail.get("state") != "released"
        ):
            raise RuntimeError(
                "rejected SLURM operation did not reach physical release"
            )
        rejected_result = rejected_operation_detail.get("result")
        if (
            not isinstance(rejected_result, Mapping)
            or rejected_result.get("submission_state") != "rejected"
        ):
            raise RuntimeError("definite fake-SLURM rejection was not retained")
    finally:
        recorder.python("LocalDaemonSocketServer.stop", first_server.stop)
        recorder.python("LocalDaemon.stop", first.stop)
    assert_processes_dead(recorder.started_pids)

    replacement = LocalDaemon(config)
    replacement_server = LocalDaemonSocketServer(replacement, config.endpoint)
    try:
        recorder.python("LocalDaemon.start", replacement.start)
        recorder.python("LocalDaemonSocketServer.start", replacement_server.start)
        recorder.observe_process_tree(os.getpid())
        retained_rejection = recorder.cli(
            "queue",
            "daemon-operation",
            "--endpoint",
            str(config.endpoint),
            rejected_operation_id,
        )
        if retained_rejection["state"] != "released":
            raise RuntimeError("restart lost the rejected operation release")
        if len([call for call in runner.calls if call[0] == "sbatch"]) != 1:
            raise RuntimeError("restart resubmitted the rejected operation")

        accepted = recorder.cli(
            "queue",
            "daemon-submit",
            "--endpoint",
            str(config.endpoint),
            "completed-stage",
            completed_uri,
        )
        accepted_assignment = wait_until(
            lambda: _slurm_assignment(recorder, config.endpoint, accepted, "accepted"),
            timeout=15,
        )
        operation_id = str(accepted_assignment["operation_id"])
        operation = recorder.cli(
            "queue",
            "daemon-operation",
            "--endpoint",
            str(config.endpoint),
            operation_id,
        )
        result = operation.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("SLURM operation detail has no typed result")
        assignment_id = str(result["assignment_id"])
        job_id = str(result["job_id"])
        request_digest = str(result["request_digest"])
        capability = base64.b64encode(capability_path.read_bytes()).decode("ascii")
        incarnation = "example-bootstrap-1"
        view = recorder.python(
            "LocalDaemon.slurm_bootstrap_view",
            lambda: replacement.slurm_bootstrap_view(
                LocalDaemonPrincipal(
                    "slurm-principal",
                    LocalDaemonRole.SLURM_BOOTSTRAP,
                    "slurm-credential",
                )
            ),
        )
        registration = recorder.python(
            "LocalDaemonSlurmBootstrapView.register",
            lambda: view.register(
                operation_id=operation_id,
                request_digest=request_digest,
                job_id=job_id,
                cluster="example-cluster",
                incarnation=incarnation,
                capability=capability,
            ),
        )
        delivery = SlurmStageDelivery.from_dict(registration["delivery"])
        workspace = recorder.python(
            "SlurmBootstrapWorkspace",
            lambda: SlurmBootstrapWorkspace(root / "compute", assignment_id),
        )
        workspace.persist_delivery(delivery)
        recorder.python(
            "LocalDaemonSlurmBootstrapView.inputs_ready",
            lambda: view.inputs_ready(assignment_id, incarnation),
        )
        fence = recorder.python(
            "LocalDaemonSlurmBootstrapView.grant",
            lambda: view.grant(assignment_id, incarnation),
        )
        permitted = recorder.python(
            "LocalDaemonSlurmBootstrapView.start_permit",
            lambda: view.start_permit(assignment_id, incarnation, fence),
        )
        if permitted is not True:
            raise RuntimeError("SLURM bootstrap start was not permitted")
        recorder.python(
            "LocalDaemonSlurmBootstrapView.started",
            lambda: view.started(
                assignment_id, incarnation, fence, "example-slurm-process"
            ),
        )
        worker_result = recorder.python(
            "execute_resident_stage_worker_request",
            lambda: execute_resident_stage_worker_request(
                worker_request=workspace.worker_request(),
                workspace_root=workspace.root,
            ),
        )
        report = workspace.retain_result(worker_result)
        recorder.python(
            "LocalDaemonSlurmBootstrapView.declare_report",
            lambda: view.declare_report(assignment_id, incarnation, fence, report),
        )
        for output in report.outputs:
            offset = 0
            while True:
                data, final = workspace.output_chunk(output.transfer_id, offset)
                offset = recorder.python(
                    "LocalDaemonSlurmBootstrapView.output_chunk",
                    lambda data=data, final=final, offset=offset: view.output_chunk(
                        assignment_id,
                        incarnation,
                        output.transfer_id,
                        offset=offset,
                        data=data,
                        final=final,
                    ),
                )
                if final:
                    break
        recorder.python(
            "LocalDaemonSlurmBootstrapView.commit_result",
            lambda: view.commit_result(assignment_id, incarnation, fence),
        )
        recorder.python(
            "LocalDaemonSlurmBootstrapView.release",
            lambda: view.release(assignment_id, incarnation),
        )
        completed = recorder.cli(
            "queue",
            "daemon-wait",
            "--endpoint",
            str(config.endpoint),
            "completed-stage",
            "--timeout",
            "15",
        )
        released = recorder.cli(
            "queue",
            "daemon-operation-wait",
            "--endpoint",
            str(config.endpoint),
            operation_id,
            "--timeout",
            "15",
        )
        if completed["state"] != "SUCCEEDED":
            raise RuntimeError("fake-SLURM result did not complete the run")
        released_operation = released.get("operation")
        if (
            not isinstance(released_operation, Mapping)
            or released_operation.get("state") != "released"
        ):
            raise RuntimeError("successful SLURM result did not physically release")
        if capability_path.exists():
            raise RuntimeError("SLURM capability was not revoked on release")
        if len([call for call in runner.calls if call[0] == "sbatch"]) != 2:
            raise RuntimeError(
                "journey did not submit exactly one rejected and one result run"
            )
    finally:
        recorder.python("LocalDaemonSocketServer.stop", replacement_server.stop)
        recorder.python("LocalDaemon.stop", replacement.stop)
    assert_processes_dead(recorder.started_pids)
    recorder.emit(
        rejected_operation_id=rejected_operation_id,
        completed_operation_id=operation_id,
        rejected=True,
        restarted=True,
        result="SUCCEEDED",
        released=True,
        root=str(root),
    )


def _prepare_run(
    recorder: JourneyRecorder,
    run_root: Path,
    name: str,
    profile: SlurmReadyStageProfile,
) -> str:
    store = LocalRunStore(run_root)
    run_uri = path_to_run_uri(run_root / name)
    store.create_run(run_uri)
    config = {
        "name": f"managed-ready-stage-{name}",
        "stages": [
            {
                "name": "produce",
                "factory": {"_target_": "run_managed_ready_stage_slurm.ProduceStage"},
                "resources": {
                    "entries": {"cpu": {"kind": "cpu", "amount": 1, "unit": "count"}}
                },
                "placement": {
                    "execution_route": {"kind": "slurm", "profile": "training"}
                },
                "outputs": {"data": {"artifact_type": "json", "codec_key": "json.v1"}},
            }
        ],
    }
    pipeline = PipelineSpec.from_config(config)
    plan = plan_pipeline(
        pipeline,
        run_uri=run_uri,
        run_store=store,
        artifact_store=LocalArtifactStore(store.local_artifact_root(run_uri)),
        persist=True,
    )
    store.write_runtime_metadata(
        run_uri, {"executor": "local", "stages": {"produce": {"executor": "local"}}}
    )
    store.write_config_snapshot(
        run_uri, "resolved", json_dumps_pretty({"pipeline": config})
    )
    recorder.python(
        "prepare_managed_local_runtime_record",
        lambda: prepare_managed_local_runtime_record(
            store=store,
            run_uri=run_uri,
            plan=plan,
            pipeline=pipeline,
            execution_requirements={
                "produce": ExecutionRequirement(
                    "example-project", "example-environment", "example-executor"
                )
            },
            slurm_profiles=(profile,),
        ),
    )
    recorder.python(
        "initialize_embedded_coordinator_authority",
        lambda: initialize_embedded_coordinator_authority(run_uri),
    )
    return run_uri


def _slurm_assignment(
    recorder: JourneyRecorder,
    endpoint: Path,
    admission: Mapping[str, object],
    state: str,
) -> dict[str, object] | None:
    admission_id = str(admission["admission_id"])
    detail = recorder.cli(
        "queue", "daemon-admission", "--endpoint", str(endpoint), admission_id
    )
    owners = detail.get("owners")
    if not isinstance(owners, dict):
        return None
    assignment_owner = owners.get("slurm")
    if not isinstance(assignment_owner, dict):
        return None
    assignments = assignment_owner.get("assignments")
    if not isinstance(assignments, list):
        return None
    for assignment in assignments:
        if (
            isinstance(assignment, dict)
            and assignment.get("target") == "slurm"
            and assignment.get("state") == state
        ):
            return assignment
    return None


if __name__ == "__main__":
    main()
