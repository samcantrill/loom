"""Unit tests for Apptainer SIF build helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import pytest

from loom.pipeline.executors.apptainer import (
    ApptainerBuildOptions,
    ApptainerCommandResult,
    ApptainerContainerBuilder,
    ApptainerOptionError,
    FakeApptainerCommandRunner,
    build_apptainer_build_command,
)
from loom.pipeline.executors.containers import (
    ContainerBuildCommandProjection,
    ContainerBuildFailure,
    ContainerBuildOutputRef,
    ContainerBuildPolicy,
    ContainerBuildRequest,
    ContainerBuildSource,
    ContainerBuildTarget,
)


pytestmark = pytest.mark.unit


def _target(*, policy: str = "always") -> ContainerBuildTarget:
    return ContainerBuildTarget(
        name="analysis-env",
        runtime="apptainer",
        source=ContainerBuildSource(kind="definition_file", path="containers/a.def"),
        output=ContainerBuildOutputRef(
            kind="apptainer_sif",
            path=".loom/containers/a.sif",
        ),
        policy=ContainerBuildPolicy(mode=policy),
    )


def test_apptainer_build_command_uses_sif_output_and_source() -> None:
    command = build_apptainer_build_command(
        ContainerBuildRequest(target=_target(), requested_by="unit-test"),
        options=ApptainerBuildOptions(
            command="singularity",
            fakeroot=True,
            force=True,
            notest=True,
        ),
    )

    assert command.argv == (
        "singularity",
        "build",
        "--fakeroot",
        "--force",
        "--notest",
        ".loom/containers/a.sif",
        "containers/a.def",
    )
    assert command.redacted_argv == command.argv


def test_apptainer_builder_reuses_current_sif(tmp_path: Path) -> None:
    source = tmp_path / "containers" / "a.def"
    output = tmp_path / ".loom" / "containers" / "a.sif"
    source.parent.mkdir(parents=True)
    output.parent.mkdir(parents=True)
    source.write_text("Bootstrap: docker\n", encoding="utf-8")
    output.write_text("sif", encoding="utf-8")
    runner = FakeApptainerCommandRunner()
    builder = ApptainerContainerBuilder(runner=runner, workspace_root=tmp_path)

    result = builder.build(
        ContainerBuildRequest(target=_target(policy="if_stale"), requested_by="test")
    )

    assert result.status == "reused"
    assert runner.calls == []


def test_apptainer_builder_builds_stale_sif(tmp_path: Path) -> None:
    source = tmp_path / "containers" / "a.def"
    output = tmp_path / ".loom" / "containers" / "a.sif"
    source.parent.mkdir(parents=True)
    output.parent.mkdir(parents=True)
    output.write_text("old", encoding="utf-8")
    source.write_text("new", encoding="utf-8")
    os.utime(output, (1_700_000_000, 1_700_000_000))
    os.utime(source, (1_700_000_100, 1_700_000_100))
    runner = FakeApptainerCommandRunner()
    builder = ApptainerContainerBuilder(runner=runner, workspace_root=tmp_path)

    result = builder.build(
        ContainerBuildRequest(target=_target(policy="if_stale"), requested_by="test")
    )

    assert result.status == "built"
    assert len(runner.calls) == 1
    command = cast(ContainerBuildCommandProjection, result.command)
    assert command.argv[-2:] == (".loom/containers/a.sif", "containers/a.def")


def test_apptainer_builder_reports_missing_source(tmp_path: Path) -> None:
    builder = ApptainerContainerBuilder(
        runner=FakeApptainerCommandRunner(),
        workspace_root=tmp_path,
    )

    result = builder.build(
        ContainerBuildRequest(target=_target(policy="always"), requested_by="test")
    )

    assert result.status == "failed"
    assert cast(ContainerBuildFailure, result.failure).code == (
        "container_build.source_missing"
    )


def test_apptainer_builder_reports_command_failure(tmp_path: Path) -> None:
    source = tmp_path / "containers" / "a.def"
    source.parent.mkdir(parents=True)
    source.write_text("Bootstrap: docker\n", encoding="utf-8")
    runner = FakeApptainerCommandRunner(
        scripted_results=[
            ApptainerCommandResult(
                command="apptainer",
                argv=("apptainer", "build", "a.sif", "a.def"),
                redacted_argv=("apptainer", "build", "a.sif", "a.def"),
                returncode=1,
                error="failed",
            )
        ]
    )
    builder = ApptainerContainerBuilder(runner=runner, workspace_root=tmp_path)

    result = builder.build(ContainerBuildRequest(target=_target(), requested_by="test"))

    assert result.status == "failed"
    assert cast(ContainerBuildFailure, result.failure).code == (
        "container_build.apptainer_failed"
    )


def test_apptainer_build_rejects_build_args() -> None:
    target = ContainerBuildTarget(
        name="analysis-env",
        runtime="apptainer",
        source={"kind": "definition_file", "path": "containers/a.def"},
        output={"kind": "apptainer_sif", "path": ".loom/containers/a.sif"},
        build_args={"TOKEN": "secret"},
    )

    with pytest.raises(ApptainerOptionError, match="build_args"):
        build_apptainer_build_command(
            ContainerBuildRequest(target=target, requested_by="test")
        )
