"""Capability checks do not borrow exclusive scheduling claims."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import json
import sys

import pytest

from loom.fleet._gpu_capability import gpu_capability
from loom.pipeline.executors.apptainer.commands import SubprocessApptainerExecRunner
from loom.queue._remote_stage_execution import GpuDeviceDescriptor, ResidentGpuDevice
from tests.unit.loom.queue.test_remote_stage_execution import _profile

pytestmark = pytest.mark.unit
DEVICE = "GPU-18cf22d0-ba80-55a5-f8d8-cb19fe940cd1"


@pytest.mark.parametrize("wrong_uuid,returncode", [(False, 0), (True, 0), (False, 1)])
def test_capability_uses_uuid_bound_container_without_claim(
    tmp_path, monkeypatch, wrong_uuid, returncode
):
    image = tmp_path / "candidate.sif"
    image.write_bytes(b"command fixture")
    profile = replace(
        _profile(tmp_path),
        gpu_devices=(ResidentGpuDevice(GpuDeviceDescriptor(DEVICE, "test", 1024), DEVICE),),
        container={
            "kind": "apptainer",
            "container": {"image": {"reference": str(image)}},
            "options": {"command": sys.executable},
            "python_executable": "/image/bin/python",
            "daemon_endpoint": None,
        },
    )
    calls = []

    def run(_runner, command, **kwargs):
        calls.append(command)
        assert "--nv" in command.argv
        assert f"CUDA_VISIBLE_DEVICES={DEVICE}" in command.argv
        index = command.argv.index(str(image))
        Path(command.argv[index + 4]).write_text(json.dumps({
            "outcome": "passed",
            "device_uuid": "GPU-other" if wrong_uuid else DEVICE,
            "device_count": 1,
            "result": [[19.0, 22.0], [43.0, 50.0]],
        }))
        return SimpleNamespace(error=None, returncode=returncode, timed_out=False)

    monkeypatch.setattr(SubprocessApptainerExecRunner, "run", run)
    result = gpu_capability(profile)
    assert len(calls) == 1
    assert result["outcome"] == ("passed" if not wrong_uuid and returncode == 0 else "failed")
    assert result["exclusive_scheduling"] == "not_tested"
    assert result["contained"] is True
    assert not list(tmp_path.rglob("*journal*"))


def test_capability_requires_declared_device(tmp_path):
    result = gpu_capability(_profile(tmp_path))
    assert result["outcome"] == "unsupported"
    assert result["code"] == "no_healthy_declared_gpu"


def test_host_capability_binds_profile_and_refuses_uncertain_replay(tmp_path, monkeypatch):
    from loom.fleet import _gpu_capability, _host
    from loom.queue import deployment
    from loom.queue.errors import QueueConflictError

    profile = _profile(tmp_path)
    monkeypatch.setattr(_host, "role", lambda request: "agent")
    monkeypatch.setattr(_host, "config", lambda request: tmp_path / "agent.json")
    monkeypatch.setattr(_host, "environment", lambda request: None)
    monkeypatch.setattr(
        deployment, "load_outbound_agent_service_config",
        lambda *a, **kw: SimpleNamespace(
            client=SimpleNamespace(resident_profiles=(profile,), resource_inventory=None)
        ),
    )
    selected = []
    monkeypatch.setattr(
        _gpu_capability, "gpu_capability",
        lambda profile: selected.append(profile) or {"outcome": "passed"},
    )
    request = {"action": "gpu-capability", "profile": profile.descriptor.to_dict()}
    assert _host.execute(request, False, tmp_path) == {"outcome": "passed"}
    assert selected == [profile]
    with pytest.raises(QueueConflictError, match="completion unknown"):
        _host.execute(request, True, tmp_path)
    request["profile"] = {**request["profile"], "revision": "different"}
    with pytest.raises(QueueConflictError, match="differs"):
        _host.execute(request, False, tmp_path)
    assert selected == [profile]


@pytest.mark.parametrize("changed_image", [False, True])
@pytest.mark.parametrize("selected_inputs", [False, True])
def test_submitted_gpu_probe_uses_exact_image_and_native_inventory(tmp_path, monkeypatch, changed_image, selected_inputs):
    from loom.fleet import _host
    from loom.queue import deployment
    from loom.queue.agent_session_transport import AgentResourceInventory
    from tests.integration.queue.test_submitted_container_agents import _fixture, _config

    policy, execution, _ = _fixture(tmp_path)
    if selected_inputs:
        from loom.queue.submitted_execution import SELECTED_INPUT_WORKER_CONTRACT

        dataset = tmp_path / "unselected"
        dataset.mkdir()
        policy = replace(policy, worker_contracts=(SELECTED_INPUT_WORKER_CONTRACT,),
            shared_roots={**policy.shared_roots, "unselected": {
                "host_path": str(dataset), "container_path": "/loom/unselected", "access": "ro",
                "qualification": {"kind": "input_directory"},
            }})
        execution = replace(execution, worker_contract=SELECTED_INPUT_WORKER_CONTRACT)
    from loom.pipeline.executors.containers import ContainerMount

    scratch_base = tmp_path / "absent-production-scratch"
    policy = replace(policy, mounts=(ContainerMount(source=str(scratch_base), target="/tmp", mode="rw"),),
                     temporary_mounts=("/tmp",), environment={"TMPDIR": "/tmp"})
    temporary_sources = []
    inventory = AgentResourceInventory(2, gpu_devices=(ResidentGpuDevice(
        GpuDeviceDescriptor(DEVICE, "test", 1024), DEVICE),))
    client = _config(tmp_path, policy, inventory)
    assert client.resident_profiles == ()
    monkeypatch.setattr(_host, "role", lambda request: "agent")
    monkeypatch.setattr(_host, "config", lambda request: tmp_path / "agent.json")
    monkeypatch.setattr(_host, "environment", lambda request: None)
    monkeypatch.setattr(deployment, "load_outbound_agent_service_config", lambda *a, **kw: SimpleNamespace(client=client))
    image = tmp_path / "workloads/aaa/image.sif"
    calls = []

    def run(_runner, command, **kwargs):
        calls.append(command)
        assert "--nv" in command.argv
        assert not any("/loom/unselected" in argument for argument in command.argv)
        assert f"CUDA_VISIBLE_DEVICES={DEVICE}" in command.argv
        index = command.argv.index(str(image))
        assert command.argv[index + 1] == execution.python_executable
        mount = next(value for value in command.argv if value.endswith(":/tmp:rw"))
        source = Path(mount.removesuffix(":/tmp:rw"))
        assert source.is_relative_to("/tmp") and source.is_dir()
        assert source != scratch_base
        temporary_sources.append(source)
        Path(command.argv[index + 4]).write_text(json.dumps({
            "outcome": "passed", "device_uuid": DEVICE, "device_count": 1,
            "result": [[19.0, 22.0], [43.0, 50.0]],
        }))
        return SimpleNamespace(error=None, returncode=0, timed_out=False)

    monkeypatch.setattr(SubprocessApptainerExecRunner, "run", run)
    if changed_image:
        image.chmod(0o600)
        image.write_bytes(b"changed")
        image.chmod(0o444)
    result = _host.execute({"action": "gpu-capability", "profile": policy.capability.to_dict(),
                            "execution": execution.to_dict()}, False, tmp_path)
    assert result["outcome"] == ("failed" if changed_image else "passed")
    assert len(calls) == (0 if changed_image else 1)
    assert result["execution"] == execution.to_dict()
    assert result["exclusive_scheduling"] == "not_tested"
    assert not client.agent_root.exists()
    assert not scratch_base.exists()
    assert all(not source.exists() for source in temporary_sources)
