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
