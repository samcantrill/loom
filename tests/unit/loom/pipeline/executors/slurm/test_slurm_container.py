"""Unit tests for SLURM and Apptainer command composition."""

from __future__ import annotations


import pytest

from loom.pipeline.executors.containers import (
    ContainerOptions,
    ContainerResourceIntent,
)
from loom.pipeline.runtime.capabilities import ResourceCapability
from loom.pipeline.executors.slurm import (
    SlurmCommandArgv,
    wrap_slurm_command_with_apptainer,
)
from loom.pipeline.executors.slurm.errors import SlurmPlanningError
from loom.pipeline.resources import ResourceEntry, ResourceRequest


pytestmark = pytest.mark.unit


def test_wrap_slurm_command_with_apptainer_preserves_worker_argv_and_redacts() -> None:
    command = SlurmCommandArgv(
        launcher_argv=("loom",),
        command_args=(
            "stage-job",
            "run",
            "--run-uri",
            "file:///runs/run-1",
            "--stage",
            "analysis",
            "--executor",
            "local",
        ),
    )

    wrapped = wrap_slurm_command_with_apptainer(
        command,
        container_options={
            "image": {"reference": "analysis.sif"},
            "workdir": "/workspace",
            "mounts": [
                {"source": "/workspace", "target": "/workspace", "mode": "rw"},
            ],
            "environment": {"variables": {"TOKEN": "secret"}},
        },
        apptainer_options={"command": "singularity", "nv": True},
    )

    assert wrapped.argv == (
        "singularity",
        "exec",
        "--cleanenv",
        "--nv",
        "--pwd",
        "/workspace",
        "--bind",
        "/workspace:/workspace:rw",
        "--env",
        "TOKEN=secret",
        "analysis.sif",
        "loom",
        "stage-job",
        "run",
        "--run-uri",
        "file:///runs/run-1",
        "--stage",
        "analysis",
        "--executor",
        "local",
    )
    assert wrapped.metadata["container_runtime"] == "apptainer"
    assert wrapped.metadata["wrapped_command_argv"] == list(command.argv)
    assert "TOKEN=[redacted]" in repr(wrapped.metadata)
    assert "TOKEN=secret" not in repr(wrapped.metadata)
    assert wrapped.to_dict()["metadata"] == dict(wrapped.metadata)


def test_slurm_gpu_wrapper_derives_nv_and_rejects_authored_visibility() -> None:
    command = SlurmCommandArgv(launcher_argv=("loom",), command_args=("--version",))
    resources = ResourceRequest(entries={"gpu": ResourceEntry(kind="gpu", amount=1)})

    wrapped = wrap_slurm_command_with_apptainer(
        command,
        container_options={"image": {"reference": "analysis.sif"}},
        apptainer_options={"cleanenv": True},
        resources=resources,
    )

    assert "--nv" in wrapped.argv
    with pytest.raises(SlurmPlanningError, match="owned by Loom"):
        wrap_slurm_command_with_apptainer(
            command,
            container_options={
                "image": {"reference": "analysis.sif"},
                "environment": {"variables": {"CUDA_VISIBLE_DEVICES": "0"}},
            },
            resources=resources,
        )


def test_slurm_container_wrapper_keeps_cpu_memory_limits_with_scheduler() -> None:
    command = SlurmCommandArgv(launcher_argv=("loom",), command_args=("--version",))
    intent = ContainerResourceIntent(
        entries={
            "cpu": ResourceEntry(kind="cpu", amount=2),
            "memory": ResourceEntry(kind="memory", amount=512, unit="MiB"),
        },
        capabilities={
            kind: ResourceCapability(support_level="supported")
            for kind in ("cpu", "memory")
        },
    )

    wrapped = wrap_slurm_command_with_apptainer(
        command,
        container_options=ContainerOptions(image="analysis.sif", resources=intent),
    )

    assert "--cpus" not in wrapped.argv
    assert "--memory" not in wrapped.argv


def _container_build_options() -> dict[str, object]:
    return {
        "targets": {
            "analysis-env": {
                "runtime": "apptainer",
                "source": {
                    "kind": "definition_file",
                    "path": "containers/analysis.def",
                },
                "output": {
                    "kind": "apptainer_sif",
                    "path": ".loom/containers/analysis.sif",
                },
                "policy": {"mode": "never"},
            }
        }
    }
