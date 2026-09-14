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
