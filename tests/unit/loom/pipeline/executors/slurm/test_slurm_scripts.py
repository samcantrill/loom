"""Unit tests for SLURM dry-run script rendering."""

from __future__ import annotations

import os
import subprocess
from typing import cast

import pytest

from loom.pipeline.executors.slurm import (
    SlurmCommandArgv,
    SlurmMode,
    SlurmOptions,
    SlurmPlannedJob,
    SlurmSbatchDirective,
    build_stage_job_command_argv,
)
from loom.pipeline.executors.slurm.planning import build_single_job_planned_submission
from loom.pipeline.executors.slurm.rendering import (
    render_command_argv,
    render_dependency_value,
    render_slurm_script,
)
from loom.pipeline.resources import ResourceEntry


def test_command_renderer_shell_quotes_structured_argv() -> None:
    command = build_stage_job_command_argv(
        "file:///runs/run 1",
        "stage-a",
        launcher_argv=("uv", "run", "loom tool"),
    )

    assert render_command_argv(command) == (
        "uv run 'loom tool' stage-job run --run-uri 'file:///runs/run 1' "
        "--stage stage-a --executor local"
    )


def test_single_job_script_renders_directives_prelude_and_command() -> None:
    options = SlurmOptions(
        partition="debug",
        prelude=("module load python", "export OMP_NUM_THREADS=1"),
        extra_sbatch={"requeue": True},
    )
    submission = build_single_job_planned_submission(
        run_uri="file:///runs/run-1",
        planning_id="planning-1",
        created_at="2026-05-08T00:00:00Z",
        options=options,
        resources={
            "cpu": ResourceEntry(kind="cpu", amount=4, unit="count"),
            "memory": ResourceEntry(kind="memory", amount=16, unit="GiB"),
        },
    )

    job = cast(tuple[SlurmPlannedJob, ...], submission.jobs)[0]
    script = render_slurm_script(job, options=options)

    assert script == "\n".join(
        (
            "#!/usr/bin/env bash",
            "#SBATCH --job-name=loom-planning-1-pipeline",
            "#SBATCH --output=slurm/submissions/planning-1/logs/pipeline.stdout.log",
            "#SBATCH --error=slurm/submissions/planning-1/logs/pipeline.stderr.log",
            "#SBATCH --partition=debug",
            "#SBATCH --cpus-per-task=4",
            "#SBATCH --mem=16G",
            "#SBATCH --requeue",
            "",
            "set -euo pipefail",
            "",
            "module load python",
            "export OMP_NUM_THREADS=1",
            "",
            "loom prepared-run continue --run-uri file:///runs/run-1 --executor local",
            "",
        )
    )


def test_afterok_script_renders_logical_dependency_and_stage_job_command() -> None:
    command = build_stage_job_command_argv("file:///runs/run-1", "report")
    job = SlurmPlannedJob(
        logical_key="stage:report",
        mode=SlurmMode.AFTEROK,
        command=command,
        dependency_job_keys=("stage:extract", "stage:train"),
        sbatch_directives=(
            SlurmSbatchDirective(
                name="dependency",
                value=render_dependency_value(("stage:extract", "stage:train")),
                source="generated",
            ),
        ),
    )

    script = render_slurm_script(job, options=SlurmOptions())

    assert "#SBATCH --dependency=afterok:stage:extract:stage:train" in script
    assert (
        "loom stage-job run --run-uri file:///runs/run-1 --stage report --executor local"
        in script
    )
    assert "loom stage run" not in script


def test_afterok_gpu_script_validates_allocation_visibility_and_projects_container_env() -> (
    None
):
    command = build_stage_job_command_argv("file:///runs/run-1", "train")
    job = SlurmPlannedJob(
        logical_key="stage:train",
        mode=SlurmMode.AFTEROK,
        command=command,
        resources={"gpu": ResourceEntry(kind="gpu", amount=1).to_dict()},
        sbatch_directives=(
            SlurmSbatchDirective(name="gres", value="gpu:1", source="generated"),
        ),
    )

    script = render_slurm_script(job, options=SlurmOptions())

    assert "#SBATCH --gres=gpu:1" in script
    assert '_loom_cuda_visible_devices="${CUDA_VISIBLE_DEVICES-}"' in script
    assert '"${#_loom_cuda_devices[@]}" -ne 1' in script
    assert "duplicate visibility token" in script
    assert "APPTAINERENV_CUDA_VISIBLE_DEVICES" in script
    assert "SINGULARITYENV_CUDA_VISIBLE_DEVICES" in script
    assert "printf 'loom.gpu_visibility" not in script


@pytest.mark.parametrize(
    ("visible", "expected_returncode"),
    (
        ("GPU-abc,MIG-device-7", 0),
        (None, 78),
        ("0", 78),
        ("0,0", 78),
        ("0,", 78),
        ("-foo,0", 78),
        (".foo,0", 78),
        ("/foo,0", 78),
    ),
)
def test_afterok_gpu_script_executes_the_public_visibility_grammar(
    visible: str | None,
    expected_returncode: int,
) -> None:
    command = SlurmCommandArgv(
        launcher_argv=("bash",),
        command_args=(
            "-c",
            (
                'test "$APPTAINERENV_CUDA_VISIBLE_DEVICES" = '
                '"$CUDA_VISIBLE_DEVICES" && '
                'test "$SINGULARITYENV_CUDA_VISIBLE_DEVICES" = '
                '"$CUDA_VISIBLE_DEVICES"'
            ),
        ),
    )
    job = SlurmPlannedJob(
        logical_key="stage:train",
        mode=SlurmMode.AFTEROK,
        command=command,
        resources={"gpu": ResourceEntry(kind="gpu", amount=2).to_dict()},
    )
    script = render_slurm_script(job, options=SlurmOptions())
    environment = dict(os.environ)
    if visible is None:
        environment.pop("CUDA_VISIBLE_DEVICES", None)
    else:
        environment["CUDA_VISIBLE_DEVICES"] = visible

    result = subprocess.run(
        ("bash",),
        input=script,
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )

    assert result.returncode == expected_returncode, result.stderr
