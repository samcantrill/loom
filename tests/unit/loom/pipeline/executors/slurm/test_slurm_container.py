"""Unit tests for SLURM and Apptainer command composition."""

from __future__ import annotations

from typing import cast

import pytest

from loom.pipeline.executors.containers import (
    ContainerBuildResult,
    FakeContainerBuilder,
    LocalContainerBuildService,
)
from loom.pipeline.executors.slurm import (
    SlurmCommandArgv,
    resolve_slurm_container_target,
    wrap_slurm_command_with_apptainer,
)
from loom.pipeline.executors.slurm.errors import SlurmPlanningError


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


def test_resolve_slurm_container_target_maps_selected_sif_output() -> None:
    builder = FakeContainerBuilder(
        "apptainer",
        existing_outputs=[".loom/containers/analysis.sif"],
    )
    service = LocalContainerBuildService({"apptainer": builder})

    resolved = resolve_slurm_container_target(
        {"target": "analysis-env", "workdir": "/workspace"},
        build_options=_container_build_options(),
        build_service=service,
        requested_by="unit-test",
    )

    result = cast(ContainerBuildResult, resolved.build_result)
    assert resolved.container_options == {
        "workdir": "/workspace",
        "image": {"reference": ".loom/containers/analysis.sif"},
    }
    assert result.target_name == "analysis-env"
    assert result.status == "reused"
    assert [call.requested_by for call in builder.calls] == ["unit-test"]


def test_resolve_slurm_container_target_rejects_missing_or_wrong_targets() -> None:
    service = LocalContainerBuildService(
        {
            "docker": FakeContainerBuilder("docker"),
            "apptainer": FakeContainerBuilder("apptainer"),
        }
    )

    with pytest.raises(SlurmPlanningError, match="not defined"):
        resolve_slurm_container_target(
            {"target": "missing"},
            build_options=_container_build_options(),
            build_service=service,
            requested_by="unit-test",
        )
    with pytest.raises(SlurmPlanningError, match="requires an apptainer"):
        resolve_slurm_container_target(
            {"target": "docker-env"},
            build_options={
                "targets": {
                    "docker-env": {
                        "runtime": "docker",
                        "source": {"kind": "docker_context", "context_path": "."},
                        "output": {
                            "kind": "docker_image",
                            "reference": "example/image:latest",
                        },
                    }
                }
            },
            build_service=service,
            requested_by="unit-test",
        )


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
