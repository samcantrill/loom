"""Tests for fakeable SLURM command runner contracts."""

from __future__ import annotations

import pytest

from loom.pipeline.executors.slurm import (
    MAX_PERSISTED_COMMAND_OUTPUT_CHARS,
    FakeSlurmCommandRunner,
    SlurmCommandResult,
    SlurmCommandUnavailableError,
    SlurmJobIdParseError,
    bound_scheduler_output,
    parse_sbatch_parsable_output,
)


def test_parse_sbatch_parsable_job_id_without_cluster() -> None:
    parsed = parse_sbatch_parsable_output("123456\n")

    assert parsed.job_id == "123456"
    assert parsed.cluster is None
    assert parsed.raw_output == "123456\n"


def test_parse_sbatch_parsable_job_id_with_cluster() -> None:
    parsed = parse_sbatch_parsable_output("123456;debug-cluster\n")

    assert parsed.job_id == "123456"
    assert parsed.cluster == "debug-cluster"


def test_parse_sbatch_parsable_rejects_unparseable_output() -> None:
    with pytest.raises(SlurmJobIdParseError):
        parse_sbatch_parsable_output("Submitted batch job 123456\n")


def test_scheduler_output_is_bounded_and_control_safe() -> None:
    output = "a" * (MAX_PERSISTED_COMMAND_OUTPUT_CHARS + 32) + "\x00"

    bounded = bound_scheduler_output(output)

    assert len(bounded) == MAX_PERSISTED_COMMAND_OUTPUT_CHARS
    assert bounded.endswith("...[truncated]")
    assert "\x00" not in bounded


def test_fake_runner_records_sbatch_dependency_call() -> None:
    runner = FakeSlurmCommandRunner(starting_job_id=42)

    result = runner.sbatch("/runs/demo/slurm/job.sh", dependency_job_ids=("1", "2"))

    assert result.ok is True
    assert parse_sbatch_parsable_output(result.stdout).job_id == "42"
    assert runner.calls == [
        (
            "sbatch",
            (
                "sbatch",
                "--parsable",
                "--dependency=afterok:1:2",
                "/runs/demo/slurm/job.sh",
            ),
        )
    ]


def test_fake_runner_can_script_failures_and_unavailable_commands() -> None:
    result = SlurmCommandResult(
        command="sbatch",
        argv=("sbatch", "--parsable", "job.sh"),
        returncode=1,
        stderr="partition unavailable",
    )
    runner = FakeSlurmCommandRunner(
        scripted_results={"sbatch": (result,)},
        unavailable_commands=("squeue",),
    )

    assert runner.sbatch("job.sh").returncode == 1
    with pytest.raises(SlurmCommandUnavailableError):
        runner.squeue()


def test_fake_runner_records_status_query_arguments() -> None:
    runner = FakeSlurmCommandRunner()

    runner.sacct(job_ids=("1", "2"))
    runner.squeue(job_ids=("1", "2"))

    assert runner.calls == [
        (
            "sacct",
            (
                "sacct",
                "--noheader",
                "--parsable2",
                "--format",
                "JobIDRaw,State,ExitCode",
                "--jobs",
                "1,2",
            ),
        ),
        (
            "squeue",
            (
                "squeue",
                "--noheader",
                "--format",
                "%i|%T|%r",
                "--jobs",
                "1,2",
            ),
        ),
    ]
