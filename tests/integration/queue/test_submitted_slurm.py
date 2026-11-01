"""Submitted Slurm dispatch, worker, and shared commit across coordinator restart."""

import base64
from dataclasses import replace
import hashlib
from pathlib import Path
import sys
from time import monotonic, sleep

import pytest

from examples.execution.containers.apptainer_fixture import fake_apptainer
from loom.pipeline.runtime.options import RunOptions
from loom.pipeline.status import StageStatus
from loom.preparation import decode_preparation_report, prepare_child_run
from loom.queue import (
    LocalDaemon,
    LocalDaemonAdmissionRequest,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
)
from loom.queue._slurm_submitted_worker import run_submitted_stage
from loom.queue._submitted_container_policy import SubmittedContainerPolicy
from loom.queue.managed_local_preparation import prepare_managed_run
from loom.queue.slurm_ready_stage import SlurmBootstrapWorkspace, SlurmStageDelivery
from tests.integration.queue import test_submitted_preparation as preparation_fixture
from tests.integration.queue.test_slurm_ready_stage import (
    _launch_profile,
    _positive_containment_helper,
)

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@pytest.mark.parametrize("preparation", [False, True])
def test_submitted_slurm_dispatch_worker_and_shared_commit_restart(
    tmp_path, monkeypatch, preparation
):
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[3]))
    original_fixture = preparation_fixture._fixture
    with fake_apptainer() as runtime:
        # The fake runtime has no mount namespace. Translate only the fixed
        # preparation snapshot lookup; shared paths use the existing fake namespace seam.
        executable = Path(runtime["options"]["command"])
        shim = (
            "import loom.queue.shared_execution as shared; "
            "shared.execution_roots = lambda roots, container: roots; "
            "original = shared.materialize; "
            "shared.materialize = lambda value, roots, container: original(value, roots, container=False); "
            "shared._preparation_input_roots = lambda profile, preparation: {key: str(value) for key, value in profile.preparation_shared_roots.items()}; "
            "import runpy; runpy.run_module('loom.queue._slurm_submitted_worker', run_name='__main__')"
        )
        executable.write_text(
            executable.read_text().replace(
                "os.execvpe(args[0], args, os.environ)",
                f"os.execvpe(args[0], [args[0], '-c', {shim!r}, *args[3:]], os.environ)",
            )
        )

        def fixture(path):
            policy, execution, request = original_fixture(path)
            output = path / "published"
            output.mkdir()
            (output / "challenge").write_bytes(b"published")
            roots = dict(policy.shared_roots)
            captures = path / "captures"
            captures.mkdir()
            (captures / "challenge").write_bytes(b"captures")
            roots["captures"] = {
                "host_path": str(captures),
                "container_path": "/loom/captures",
                "access": "ro",
                "challenge": {
                    "path": "challenge",
                    "sha256": hashlib.sha256(b"captures").hexdigest(),
                },
            }
            roots["outputs"] = {
                "host_path": str(output),
                "container_path": "/loom/outputs",
                "access": "rw",
                "challenge": {
                    "path": "challenge",
                    "sha256": hashlib.sha256(b"published").hexdigest(),
                },
                "publication": {
                    "max_members": 128,
                    "max_payload_bytes": 1024**3,
                    "max_manifest_bytes": 1024**2,
                },
            }
            return (
                replace(
                    policy,
                    shared_roots=roots,
                    runtime_options=runtime["options"],
                    preparation_shared_roots={"projects": path / "captures"},
                ),
                replace(execution, python_executable=sys.executable),
                request,
            )

        monkeypatch.setattr(preparation_fixture, "_fixture", fixture)
        service, binding, report = preparation_fixture._run(
            tmp_path,
            monkeypatch,
            slurm=True,
            stage_update={
                "placement": {"execution_route": {"kind": "slurm", "profile": "batch"}}
            },
        )
        service = replace(
            service,
            daemon=replace(
                service.daemon,
                slurm_profiles=(
                    replace(
                        service.daemon.slurm_profiles[0],
                        containment_helper=_positive_containment_helper(),
                    ),
                ),
            ),
        )
        if preparation:
            prepared = prepare_child_run(
                service, binding, "child", runtime_options=RunOptions(executor="local")
            )
        else:
            composed, requirements, _ = decode_preparation_report(
                report, expected=binding
            )
            prepared = prepare_managed_run(
                service, composed, "workload", execution_requirements=requirements
            )
        profile = service.daemon.slurm_profiles[0]
        config = LocalDaemonConfig(
            coordinator_root=tmp_path / "daemon/coordinator",
            agent_root=tmp_path / "daemon/agent",
            run_store_root=service.daemon.run_store_root,
            resident_worker_launch_profile=_launch_profile(),
            slurm_profiles=(profile,),
            shared_roots=service.daemon.shared_roots,
            container_capabilities=service.daemon.container_capabilities,
        )
        LocalDaemon.initialize(config)
        daemon = LocalDaemon(config)
        daemon.start()
        try:
            client = daemon.client_view(
                LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
            )
            client.submit(LocalDaemonAdmissionRequest("submitted", prepared.run_uri))
            deadline = monotonic() + 10
            records = ()
            while monotonic() < deadline:
                records = daemon._execution.slurm_assignments.list_run_unreleased(
                    prepared.run_uri
                )
                if records and records[0].state == "accepted":
                    break
                sleep(0.02)
            assert records and records[0].state == "accepted"
            record = records[0]
            operation = daemon.operation(record.assignment.operation_id)
            assert operation.result["job_id"] == record.job_id
            assert (
                len([call for call in profile.runner.calls if call[0] == "sbatch"]) == 1
            )
            daemon.stop()
            daemon = LocalDaemon(config)
            daemon.start()
            principal = LocalDaemonPrincipal(
                profile.bootstrap_principal_id,
                LocalDaemonRole.SLURM_BOOTSTRAP,
                profile.credential_reference,
            )
            view = daemon.slurm_bootstrap_view(principal)
            registration = view.register(
                operation_id=record.assignment.operation_id,
                request_digest=record.assignment.request_digest,
                job_id=record.job_id,
                cluster=record.cluster,
                incarnation="compute-1",
                capability=base64.b64encode(
                    Path(profile.job_private_file_provider.fixed_path).read_bytes()
                ).decode(),
            )
            delivery = SlurmStageDelivery.from_dict(registration["delivery"])
            assert delivery.submitted_execution == binding.execution
            policy = SubmittedContainerPolicy.from_dict(
                registration["submitted_container_policy"]
            )
            assert policy.capability == binding.container_capability
            workspace = SlurmBootstrapWorkspace(
                tmp_path / "compute", delivery.assignment_id
            )
            workspace.persist_delivery(delivery)
            for item in delivery.inputs:
                offset = 0
                while True:
                    data, final = view.input_chunk(
                        delivery.assignment_id,
                        "compute-1",
                        item.transfer_id,
                        offset=offset,
                    )
                    offset = workspace.stage_input_chunk(
                        item.transfer_id, offset, data, final=final
                    )
                    if final:
                        break
            workspace.accept_inputs(shared_roots=policy.shared_roots)
            assert view.inputs_ready(delivery.assignment_id, "compute-1")
            fence = view.grant(delivery.assignment_id, "compute-1")
            assert view.start_permit(delivery.assignment_id, "compute-1", fence)
            view.started(delivery.assignment_id, "compute-1", fence, "process-1")
            result = run_submitted_stage(
                workspace, policy, agent_id=record.assignment.agent_id, fence=fence
            )
            assert result.status is StageStatus.SUCCEEDED, result.failure
            retained = workspace.retain_result(result)
            assert retained.output_kind == "shared"
            view.declare_report(delivery.assignment_id, "compute-1", fence, retained)
            view.commit_result(delivery.assignment_id, "compute-1", fence)
            # A lost commit reply may replay after restart, without launching twice.
            daemon.stop()
            daemon = LocalDaemon(config)
            daemon.start()
            view = daemon.slurm_bootstrap_view(principal)
            assert not view.start_permit(delivery.assignment_id, "compute-1", fence)
            view.commit_result(delivery.assignment_id, "compute-1", fence)
            view.release(delivery.assignment_id, "compute-1")
            client = daemon.client_view(
                LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
            )
            assert (
                client.wait("submitted", timeout_seconds=10).state.value == "SUCCEEDED"
            )
            assert (
                len([call for call in profile.runner.calls if call[0] == "sbatch"]) == 1
            )
        finally:
            daemon.stop()
