"""Submitted images retain native identity while Slurm owns the allocation."""

from dataclasses import fields, replace
import hashlib
from pathlib import Path
import sys

import pytest

from loom.queue._slurm_submitted_worker import submitted_command
from loom.queue.errors import QueueConflictError, QueueServiceError
from loom.queue.slurm_ready_stage import SlurmBootstrapWorkspace, SlurmStageDelivery
from loom.pipeline.executors.apptainer.build import ApptainerOptionError
from tests.unit.loom.queue.test_submitted_container_policy import _submitted


def _workspace(tmp_path, *, gpu=False):
    policy, execution, request, image = _submitted(tmp_path)
    if gpu:
        request = replace(
            request,
            resolved_runtime={
                **request.resolved_runtime,
                "resources": {
                    "schema_version": 2,
                    "entries": {
                        "gpu": {
                            "kind": "gpu",
                            "amount": 1,
                            "unit": "count",
                            "attributes": {},
                        },
                        "cpu": {
                            "kind": "cpu",
                            "amount": 2,
                            "unit": "count",
                            "attributes": {},
                        },
                    },
                },
            },
        )
    delivery = SlurmStageDelivery(
        **{
            field.name: getattr(request, field.name)
            for field in fields(SlurmStageDelivery)
            if hasattr(request, field.name) and field.name != "schema_version"
        },
        profile_id="hpc-gpu" if gpu else "hpc-cpu",
        project_fingerprint="bootstrap-project",
        environment_fingerprint="bootstrap-environment",
        executor_fingerprint="bootstrap-executor",
    )
    workspace = SlurmBootstrapWorkspace(tmp_path / "compute", delivery.assignment_id)
    workspace.persist_delivery(SlurmStageDelivery.from_dict(delivery.to_dict()))
    workspace.stage_input_chunk("input-1", 0, b"input", final=True)
    return workspace, policy, execution, image


@pytest.mark.parametrize("gpu", [False, True])
def test_submitted_slurm_command_preserves_image_mounts_and_allocation(tmp_path, gpu):
    workspace, policy, execution, image = _workspace(tmp_path, gpu=gpu)
    command = submitted_command(
        workspace,
        policy,
        agent_id="submit-agent",
        fence="grant",
        allocation_environment={
            "CUDA_VISIBLE_DEVICES": "GPU-allocation-id",
            "LOOM_SLURM_BOOTSTRAP_CONFIG": "/secret/bootstrap.json",
        },
    )
    argv = command.argv
    assert str(image) in argv
    assert execution.python_executable in argv
    assert "loom.queue._slurm_submitted_worker" in argv
    assert "--cleanenv" in argv
    assert "--contain" in argv
    assert "--cpus" not in argv and "--memory" not in argv
    assert "/secret/bootstrap.json" not in " ".join(argv)
    assert f"{tmp_path}/input-tree:/loom/data:ro" in argv
    assert ("--nv" in argv) == gpu
    assert ("CUDA_VISIBLE_DEVICES=GPU-allocation-id" in argv) == gpu
    assert command.metadata["gpu_visibility"]["visible_gpu_count"] == (1 if gpu else 0)
    assert workspace.delivery().submitted_execution == execution
    # Reading the retained binding does not reinterpret image selection.
    from loom.queue._agent_process_supervisor import _profile_from_value

    retained = _profile_from_value(workspace.publication_binding()["profile"])
    assert retained.submitted_execution == execution
    assert retained.descriptor == policy.capability.to_dict()


def test_submitted_slurm_refuses_changed_image_and_unavailable_gpu(tmp_path):
    workspace, policy, _execution, image = _workspace(tmp_path, gpu=True)
    with pytest.raises(ApptainerOptionError, match="GPU binding"):
        submitted_command(
            workspace,
            policy,
            agent_id="submit-agent",
            fence="grant",
            allocation_environment={},
        )
    image.chmod(0o644)
    image.write_bytes(b"different image")
    image.chmod(0o444)
    with pytest.raises(
        (ValueError, QueueServiceError, QueueConflictError), match="image"
    ):
        submitted_command(
            workspace,
            policy,
            agent_id="submit-agent",
            fence="grant",
            allocation_environment={"CUDA_VISIBLE_DEVICES": "0"},
        )


def test_submitted_slurm_requires_protected_policy_and_clean_environment(tmp_path):
    workspace, policy, _execution, _image = _workspace(tmp_path)
    other = replace(policy, environment={"DIFFERENT": "policy"})
    with pytest.raises(QueueServiceError, match="not authorized"):
        submitted_command(
            workspace,
            other,
            agent_id="submit-agent",
            fence="grant",
            allocation_environment={},
        )
    unclean = replace(
        policy, runtime_options={**policy.runtime_options, "cleanenv": False}
    )
    with pytest.raises(QueueServiceError, match="clean container environment"):
        submitted_command(
            workspace,
            unclean,
            agent_id="submit-agent",
            fence="grant",
            allocation_environment={},
        )


def test_submitted_slurm_runs_worker_process_and_publishes_complete_output_tree(
    tmp_path,
):
    """Exercise a real worker with fake mount translation, not physical isolation."""
    from examples.execution.containers.apptainer_fixture import fake_apptainer
    from loom.pipeline.planning import StageFingerprintRecord
    from loom.pipeline.status import StageStatus
    from loom.queue._slurm_submitted_worker import run_submitted_stage
    from loom.queue.shared_execution import (
        SHARED_EXECUTION_SCOPE,
        qualifications,
        stage_scope,
    )
    from loom.queue.submitted_execution import SUBMITTED_EXECUTION_SCOPE
    from loom.queue._shared_publication import publish
    from loom.io.uris import uri_to_path

    old_workspace, policy, execution, _image = _workspace(tmp_path)
    delivery = old_workspace.delivery()
    package = tmp_path / "image-package"
    package.mkdir()
    (package / "pkg.py").write_text(
        "from loom.artifacts import ArtifactRef\n"
        "class Stage:\n"
        "    def run(self, context, inputs):\n"
        "        path = context.local_output_path('result')\n"
        "        path.parent.mkdir(parents=True, exist_ok=True)\n"
        "        path.write_bytes(b'container-worker-output')\n"
        "        (path.parent / 'checkpoint.bin').write_bytes(b'checkpoint')\n"
        "        return {'result': ArtifactRef('stage/result', path.as_uri(), 'bytes')}\n"
    )
    output = tmp_path / "outputs"
    output.mkdir()
    (output / "challenge").write_bytes(b"outputs")
    roots = dict(policy.shared_roots)
    roots["outputs"] = {
        "host_path": str(output),
        "container_path": "/loom/outputs",
        "access": "rw",
        "challenge": {
            "path": "challenge",
            "sha256": hashlib.sha256(b"outputs").hexdigest(),
        },
        "publication": {
            "max_members": 128,
            "max_payload_bytes": 1024 * 1024,
            "max_manifest_bytes": 65536,
        },
    }
    with fake_apptainer() as runtime:
        executable = Path(runtime["options"]["command"])
        shim = (
            "import loom.queue.shared_execution as shared; "
            "shared.execution_roots = lambda roots, container: roots; "
            "original = shared.materialize; "
            "shared.materialize = lambda value, roots, container: original(value, roots, container=False); "
            "import runpy; runpy.run_module('loom.queue._slurm_submitted_worker', run_name='__main__')"
        )
        executable.write_text(
            executable.read_text().replace(
                "os.execvpe(args[0], args, os.environ)",
                f"os.environ['PYTHONPATH'] = {str(package)!r} + os.pathsep + os.environ.get('PYTHONPATH', '')\nos.execvpe(args[0], [args[0], '-c', {shim!r}, *args[3:]], os.environ)",
            )
        )
        policy = replace(policy, shared_roots=roots, runtime_options=runtime["options"])
        execution = replace(execution, python_executable=sys.executable)
        old = StageFingerprintRecord.from_dict(delivery.fingerprint)
        scope = stage_scope(
            {
                "input": {
                    "kind": "loom.shared-location",
                    "schema_version": 1,
                    "root_id": "data",
                    "path": ".",
                }
            },
            {},
            {
                "roots": qualifications(
                    {
                        alias: root
                        for alias, root in roots.items()
                        if alias != "workloads"
                    }
                )
            },
        )
        fingerprint = StageFingerprintRecord.create(
            algorithm=old.algorithm,
            inputs_summary=old.inputs_summary,
            payload=replace(
                old.payload,
                fingerprint_fields={
                    SHARED_EXECUTION_SCOPE: scope,
                    SUBMITTED_EXECUTION_SCOPE: {
                        "execution": execution.to_dict(),
                        "container_capability": policy.capability.to_dict(),
                    },
                },
            ),
        )
        delivery = replace(
            delivery,
            assignment_id="process-assignment",
            fingerprint=fingerprint.to_dict(),
            worker_metadata={
                **delivery.worker_metadata,
                "loom.execution_binding": {
                    **delivery.worker_metadata["loom.execution_binding"],
                    "environment_fingerprint": policy.capability.environment_fingerprint,
                },
            },
        )
        workspace = SlurmBootstrapWorkspace(
            tmp_path / "process", delivery.assignment_id
        )
        workspace.persist_delivery(delivery)
        workspace.stage_input_chunk("input-1", 0, b"input", final=True)
        result = run_submitted_stage(
            workspace, policy, agent_id="submit-agent", fence="grant"
        )
    assert result.status is StageStatus.SUCCEEDED
    assert result.executor_metadata["container_runtime"] == "apptainer"
    report = workspace.retain_result(result)
    assert report.output_kind == "shared"
    committed = publish(delivery, report, roots, agent_id="submit-agent", fence="grant")
    primary = uri_to_path(committed["result"].uri)
    assert primary.read_bytes() == b"container-worker-output"
    assert (primary.parent / "checkpoint.bin").read_bytes() == b"checkpoint"
