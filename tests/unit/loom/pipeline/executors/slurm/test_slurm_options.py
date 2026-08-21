"""Unit tests for SLURM option and argv contracts."""

from __future__ import annotations

import pytest

from loom.pipeline.executors.slurm import (
    SlurmMode,
    SlurmOptionError,
    SlurmOptions,
    build_single_job_command_argv,
    build_stage_job_command_argv,
)


def test_slurm_mode_wire_values_are_stable() -> None:
    assert SlurmMode.SINGLE_JOB.value == "slurm-single-job"
    assert SlurmMode.AFTEROK.value == "slurm-afterok"


def test_options_round_trip_modeled_fields_and_launcher() -> None:
    options = SlurmOptions(
        partition="batch",
        account="acct",
        qos="normal",
        constraint="zen4",
        nodes=2,
        ntasks=4,
        cpus_per_task=8,
        mem="32G",
        mem_per_cpu=None,
        gres="gpu:1",
        time="01:00:00",
        prelude=("module load python",),
        extra_sbatch={"--mail-type": "END", "exclusive": True},
        launcher_argv=("uv", "run", "loom"),
    )

    payload = options.to_dict()

    assert payload["extra_sbatch"] == {"exclusive": True, "mail-type": "END"}
    assert payload["launcher_argv"] == ["uv", "run", "loom"]
    assert SlurmOptions.from_dict(payload) == options


def test_options_reject_unknown_fields() -> None:
    with pytest.raises(SlurmOptionError, match="unknown field"):
        SlurmOptions.from_dict({"schema_version": 1, "partition": "debug", "bad": "x"})


def test_options_reject_mutually_exclusive_memory_directives() -> None:
    with pytest.raises(SlurmOptionError, match="mem.*mem_per_cpu"):
        SlurmOptions(mem="32G", mem_per_cpu="4G")


@pytest.mark.parametrize(
    "extra, message",
    [
        ({"--partition": "debug"}, "conflicts"),
        ({"--gres": "gpu:2"}, "conflicts"),
        ({"mail": False}, "not false"),
        ({"mail": None}, "string value or true"),
        ({"mail": 1}, "string value or true"),
        ({"": "x"}, "must not be empty"),
        ({"bad flag": "x"}, "whitespace"),
        ({"bad/name": "x"}, "path separators"),
        ({"-short": "x"}, "long SBATCH"),
    ],
)
def test_extra_sbatch_validation(extra: dict[str, object], message: str) -> None:
    with pytest.raises(SlurmOptionError, match=message):
        SlurmOptions(extra_sbatch=extra)  # type: ignore[arg-type]


def test_extra_sbatch_rejects_duplicate_normalized_names() -> None:
    with pytest.raises(SlurmOptionError, match="duplicates"):
        SlurmOptions(extra_sbatch={"--mail-type": "END", "mail-type": "FAIL"})


def test_launcher_argv_defaults_and_rejects_bad_entries() -> None:
    assert SlurmOptions().launcher_argv == ("loom",)

    with pytest.raises(SlurmOptionError, match="must not be empty"):
        SlurmOptions(launcher_argv=())
    with pytest.raises(SlurmOptionError, match=r"launcher_argv\[1\]"):
        SlurmOptions(launcher_argv=("uv", ""))


def test_generated_single_job_command_targets_phase_two_command() -> None:
    command = build_single_job_command_argv(
        "file:///runs/run-1",
        launcher_argv=("uv", "run", "loom"),
    )

    assert command.argv == (
        "uv",
        "run",
        "loom",
        "prepared-run",
        "continue",
        "--run-uri",
        "file:///runs/run-1",
        "--executor",
        "local",
    )
    assert command.to_dict()["argv"] == list(command.argv)


def test_generated_stage_job_command_targets_phase_two_command() -> None:
    command = build_stage_job_command_argv("file:///runs/run-1", "build")

    assert command.argv == (
        "loom",
        "stage-job",
        "run",
        "--run-uri",
        "file:///runs/run-1",
        "--stage",
        "build",
        "--executor",
        "local",
    )


def test_generated_stage_job_command_carries_applicable_plugin_selectors() -> None:
    command = build_stage_job_command_argv(
        "file:///runs/run-1",
        "build",
        plugin_selectors=(
            "loom.codecs:stage28.tagged-json.v1",
            "loom.resource_validators:stage28.device",
        ),
    )

    assert command.command_args[-4:] == (
        "--plugin",
        "loom.codecs:stage28.tagged-json.v1",
        "--plugin",
        "loom.resource_validators:stage28.device",
    )
