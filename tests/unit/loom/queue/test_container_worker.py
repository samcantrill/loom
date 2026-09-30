"""Installed binding, resource and environment ownership at the worker boundary."""

import sys
from pathlib import Path
from typing import cast

import pytest

from loom.queue._agent_process_supervisor import ResidentWorkerLaunchProfile
from loom.queue._container_worker import build_container_worker, container_binding


def _binding():
    return {
        "kind": "docker",
        "container": {"image": {"reference": "sha256:" + "a" * 64}},
        "options": {"command": "/usr/bin/docker"},
        "python_executable": "python3",
        "daemon_endpoint": "unix:///var/run/docker.sock",
    }


def _persist_shared_workspace(tmp_path, workspace, container, roots, **kwargs):
    from dataclasses import replace
    from loom.queue._remote_stage_execution import _ResidentAssignmentWorkspace
    from tests.unit.loom.queue.test_remote_stage_execution import _profile, _request

    container = {**container, "options": {**container["options"], "command": sys.executable}}
    if container["kind"] == "apptainer":
        Path(container["container"]["image"]["reference"]).write_bytes(b"command-only SIF fixture")
    resident = replace(_profile(tmp_path), project_root=tmp_path, container=container,
                       shared_roots=roots, **kwargs)
    request = replace(_request(resident), assignment_id=workspace.name)
    _ResidentAssignmentWorkspace(workspace.parent.parent, workspace.name).persist_request(request, resident)
    return resident.launch_profile


def test_binding_rejects_mutable_image_and_ambient_daemon():
    binding = _binding()
    binding["container"]["image"]["reference"] = "latest"
    with pytest.raises(ValueError, match="immutable"):
        container_binding(binding)
    binding = _binding()
    binding["daemon_endpoint"] = None
    with pytest.raises(ValueError, match="endpoint"):
        container_binding(binding)


def test_selected_cpu_memory_and_explicit_environment_share_command_owner(
    tmp_path: Path,
):
    binding = _binding()
    binding["container"]["environment"] = {
        "variables": {"PATH": "/image/bin", "SECRET": "private"}
    }
    profile = ResidentWorkerLaunchProfile(
        tmp_path, Path(sys.executable), {"profile_id": "installed"}, container=binding
    )
    workspace = tmp_path / "agent/assignments/one"
    workspace.mkdir(parents=True)
    runtime = {
        "resources": {
            "schema_version": 2,
            "entries": {
                "cpu": {"kind": "cpu", "amount": 2, "unit": "count"},
                "memory": {"kind": "memory", "amount": 128, "unit": "MiB"},
            },
        },
        "resource_policy": {"account_for": "all", "enforce": ["cpu", "memory"]},
        "resource_selection": {
            "account_for": ["cpu", "memory"],
            "enforce": ["cpu", "memory"],
        },
    }
    command = build_container_worker(
        profile,
        workspace=workspace,
        worker=("python3", "-m", "loom.queue._resident_stage_worker"),
        environment={"PATH": "/host/python"},
        runtime=runtime,
    )
    assert "--cpus" in command.argv and "--memory" in command.argv
    assert "PATH=/image/bin" in command.argv
    assert "SECRET=private" in command.argv
    assert command.redacted_argv is not None
    assert not any("private" in item for item in command.redacted_argv)
    controls = cast(list[dict[str, object]], command.metadata["resource_controls"])
    assert {item["owner"] for item in controls} == {"docker"}
    assert {item["resource"] for item in controls} == {"cpu", "memory"}


def test_installed_project_mount_cannot_be_replaced(tmp_path: Path):
    binding = _binding()
    binding["container"]["mounts"] = [
        {"source": "/foreign", "target": str(tmp_path), "mode": "ro"}
    ]
    profile = ResidentWorkerLaunchProfile(
        tmp_path, Path(sys.executable), {"profile_id": "installed"}, container=binding
    )
    with pytest.raises(ValueError, match="path parity"):
        build_container_worker(
            profile,
            workspace=tmp_path / "agent/assignments/one",
            worker=("python3",),
            environment={},
        )


@pytest.mark.parametrize("visibility", [None, "GPU-a,GPU-b", "GPU-a,GPU-a"])
def test_managed_gpu_constraints_still_require_exact_binding(tmp_path, visibility):
    from loom.pipeline.executors.apptainer import ApptainerOptionError
    from loom.pipeline.executors.gpu_visibility import requested_gpu_count
    from loom.pipeline.resources import ResourceEntry

    gpu = ResourceEntry("gpu", 1, "count", {"models": ["model-0"]})
    with pytest.raises(ApptainerOptionError, match="attributes are unsupported"):
        requested_gpu_count({"gpu": gpu})
    profile = ResidentWorkerLaunchProfile(
        tmp_path,
        Path(sys.executable),
        {"profile_id": "installed"},
        container={
            "kind": "apptainer",
            "container": {"image": {"reference": str(tmp_path / "fixture.sif")}},
            "options": {"command": "/usr/bin/singularity"},
            "python_executable": "python3",
            "daemon_endpoint": None,
        },
    )
    with pytest.raises(
        ApptainerOptionError, match="requested GPU binding is unavailable"
    ):
        build_container_worker(
            profile,
            workspace=tmp_path,
            worker=("python3",),
            environment={}
            if visibility is None
            else {"CUDA_VISIBLE_DEVICES": visibility},
            runtime={
                "resources": {"schema_version": 2, "entries": {"gpu": gpu.to_dict()}},
                "resource_policy": {"account_for": "all", "enforce": ["gpu"]},
                "resource_selection": {"account_for": ["gpu"], "enforce": ["gpu"]},
            },
        )


def test_managed_model_filtered_gpu_launch_retains_provider_binding(tmp_path):
    import json
    from dataclasses import replace
    from loom.pipeline.runtime.scheduling_resources import GpuResourcePlanner
    from loom.queue._agent_process_supervisor import (
        ResidentWorkerLaunch,
        _launch_from_value,
        _launch_value,
    )
    from loom.queue._managed_local import (
        ClaimCommand,
        ClaimOutcome,
        GpuResourceProvider,
        ManagedAssignment,
        _worker_environment,
    )
    from loom.queue._remote_stage_execution import _ResidentAssignmentWorkspace
    from loom.scheduling import CapacityAtom, ExactQuantity, ResourceClaim
    from tests.unit.loom.queue.test_remote_stage_execution import _profile, _request

    image = tmp_path / "fixture.sif"
    image.write_bytes(b"command construction fixture")
    resident = replace(
        _profile(tmp_path),
        container={
            "kind": "apptainer",
            "container": {"image": {"reference": str(image)}},
            "options": {"command": sys.executable},
            "python_executable": "python3",
            "daemon_endpoint": None,
        },
    )
    atom = CapacityAtom(
        "gpu", "agent-1:gpu-safe", ExactQuantity(1), "count", ExactQuantity(1)
    )
    provider = GpuResourceProvider(
        GpuResourcePlanner().claim_contracts,
        (atom,),
        bindings={atom.local_capacity_key: "GPU-private"},
    )
    claim = ResourceClaim("gpu", GpuResourcePlanner().claim_contracts[0], (atom,), 1)
    original = _request(resident)
    request = replace(
        original,
        claims=(claim,),
        provider_descriptors=(provider.descriptor,),
        resolved_runtime={
            **original.resolved_runtime,
            "resources": {
                "schema_version": 2,
                "entries": {
                    "gpu": {
                        "kind": "gpu",
                        "amount": 1,
                        "unit": "count",
                        "attributes": {
                            "allocation_mode": "exclusive",
                            "models": ["model-0"],
                        },
                    },
                },
            },
            "resource_policy": {"account_for": "all", "enforce": ["gpu"]},
            "resource_selection": {"account_for": ["gpu"], "enforce": ["gpu"]},
        },
    )
    workspace = _ResidentAssignmentWorkspace(tmp_path / "agent", request.assignment_id)
    workspace.persist_request(request, resident)
    workspace.stage_input("input-1", b"input")
    workspace.accept()
    workspace.grant("fence-1")
    assignment = ManagedAssignment(
        request.assignment_id,
        "run-1",
        request.stage_work_id,
        request.stage_name,
        request.attempt,
        request.attempt_id,
        "agent-1",
        "session-1",
        request.offer_id,
        request.claim_id,
    )
    command = ClaimCommand(assignment, "prepare-1", claim, provider.descriptor)
    assert provider.prepare(command).outcome is ClaimOutcome.PREPARED
    assert provider.activate(command).outcome is ClaimOutcome.ACTIVE
    profile = resident.launch_profile
    environment = _worker_environment(
        profile,
        workspace.root,
        (command,),
        {"gpu": provider},
        request.resolved_runtime["resource_selection"],
    )
    launch = ResidentWorkerLaunch(
        "supervisor-1",
        "epoch-1",
        "agent-1",
        "session-1",
        request.assignment_id,
        "process-1",
        "fence-1",
        "launch-1",
        "a" * 64,
        workspace.root,
        profile,
        environment,
    )
    encoded = json.dumps(_launch_value(launch))
    workspace.persist_supervisor_launch(encoded)
    replay = _launch_from_value(json.loads(workspace.supervisor_launch_json()))
    assert replay.spec_digest == launch.spec_digest
    assert replay.command_argv == launch.command_argv
    assert replay.resource_controls == launch.resource_controls
    assert replay.environment["CUDA_VISIBLE_DEVICES"] == "GPU-private"
    assert "CUDA_VISIBLE_DEVICES=GPU-private" in replay.command_argv
    assert "--nv" in replay.command_argv
    assert workspace.request().to_dict() == request.to_dict()
    metadata = replay.container_command.metadata
    assert metadata["container"]["resources"]["entries"]["gpu"]["attribute_count"] == 2
    assert {
        "resource": "gpu",
        "owner": "apptainer",
        "mechanism": "cuda_visibility_binding",
        "disposition": "requested",
    } in replay.resource_controls


@pytest.mark.parametrize("runtime", ["docker", "apptainer"])
def test_shared_containers_mount_only_selected_products_in_fixed_namespace(tmp_path, runtime):
    import hashlib
    from loom.queue.shared_execution import qualifications, stage_scope
    data = tmp_path / "nas" / "data"
    other = tmp_path / "nas" / "other"
    for path in (data, other):
        path.mkdir(parents=True)
        (path / "challenge").write_bytes(b"shared")
        (path / "selected").write_bytes(b"data")
    roots = {alias: {"host_path": str(path), "container_path": "/loom/" + alias, "access": "ro",
        "challenge": {"path": "challenge", "sha256": hashlib.sha256(b"shared").hexdigest()}}
        for alias, path in (("data", data), ("other", other))}
    binding = _binding()
    if runtime == "apptainer":
        binding.update(kind="apptainer", daemon_endpoint=None)
        binding["container"]["image"]["reference"] = str(tmp_path / "installed.sif")
        binding["options"]["command"] = "/usr/bin/singularity"
    config = {"input": {"kind": "loom.shared-location", "schema_version": 1, "root_id": "data", "path": "selected"}}
    scope = stage_scope(config, {}, {"roots": qualifications(roots)})
    workspace = tmp_path / "agent" / "assignments" / "selected-attempt"
    workspace.mkdir(parents=True)
    profile = _persist_shared_workspace(tmp_path, workspace, binding, roots)
    command = build_container_worker(profile, workspace=workspace, worker=("python3", "-m", "loom.queue._resident_stage_worker"),
        environment={"PYTHONPATH": str(tmp_path / "editable")}, shared_scope=scope)
    argv = " ".join(command.argv)
    assert "/loom/data/selected" in argv and str(data / "selected") in argv
    assert str(other) not in argv and "/loom/other" not in argv
    assert "PYTHONPATH" not in argv and "PYTHONSAFEPATH=1" in argv
    if runtime == "apptainer":
        assert "--contain" in command.argv and "hostfs,bind-paths,cwd" in command.argv
    assert all("target=" + str(workspace.parent.parent) not in arg.split(",") for arg in command.argv)
    empty = stage_scope({}, {}, {"roots": qualifications(roots)})
    command = build_container_worker(profile, workspace=workspace, worker=("python3",), environment={}, shared_scope=empty)
    assert "/loom/data" not in " ".join(command.argv)


def test_shared_preparation_binds_only_immutable_capture_at_fixed_target(tmp_path):
    import hashlib
    from loom.queue.preparation import SharedInputReceipt
    from loom.queue.shared_execution import qualifications
    root = tmp_path / "private-mount" / "snapshots"
    capture = root / "capture-one"
    capture.mkdir(parents=True)
    (root / "challenge").write_bytes(b"shared")
    roots = {"snapshots": {"host_path": str(root), "container_path": "/loom/snapshots", "access": "ro",
        "challenge": {"path": "challenge", "sha256": hashlib.sha256(b"shared").hexdigest()}}}
    scope = {"capability": "shared-execution-v1", "roots": qualifications(roots), "locations": []}
    workspace = tmp_path / "agent" / "assignments" / "prepare"
    workspace.mkdir(parents=True)
    profile = _persist_shared_workspace(tmp_path, workspace, _binding(), roots,
        preparation_shared_roots={"projects": root})
    command = build_container_worker(profile, workspace=workspace, worker=("python3",), environment={}, shared_scope=scope,
        shared_snapshot=SharedInputReceipt("sha256:" + "a" * 64, "projects", "capture-one"))
    assert any("source=" + str(capture) in arg and "target=/loom/snapshots/capture-one" in arg for arg in command.argv)
    assert all("source=" + str(root) not in arg.split(",") for arg in command.argv)
