"""End-to-end scheduler-aware SLURM status through the public CLI."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from loom.cli.main import main
from loom.pipeline.executors.slurm import FakeSlurmCommandRunner, SlurmCommandResult
from tests.support.slurm_status_fixtures import write_submitted_slurm_fixture

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize(
    ("sacct_output", "squeue_output", "unavailable", "expected"),
    (
        ("", "", ("sacct", "squeue"), "SUBMITTED"),
        ("", "100|RUNNING|None\n", (), "RUNNING"),
        ("100|COMPLETED|0:0\n", "", (), "SUCCEEDED"),
        ("100|FAILED|1:0\n", "", (), "FAILED"),
        ("100|CANCELLED by 123|0:15\n", "", (), "CANCELLED"),
        ("", "100|PENDING|Dependency\n", (), "DEPENDENCY_BLOCKED"),
        ("", "100|CONFIG_ERROR|Unknown\n", (), "UNKNOWN"),
    ),
)
def test_cli_status_jobs_reports_fake_scheduler_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sacct_output: str,
    squeue_output: str,
    unavailable: tuple[str, ...],
    expected: str,
) -> None:
    import loom.cli.status as status_command

    _, run_uri, _ = write_submitted_slurm_fixture(
        tmp_path,
        {"extract": ()},
        starting_job_id=100,
    )
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "sacct": (
                SlurmCommandResult(
                    command="sacct",
                    argv=("sacct",),
                    returncode=0,
                    stdout=sacct_output,
                ),
            ),
            "squeue": (
                SlurmCommandResult(
                    command="squeue",
                    argv=("squeue",),
                    returncode=0,
                    stdout=squeue_output,
                ),
            ),
        },
        unavailable_commands=unavailable,
    )
    monkeypatch.setattr(
        status_command,
        "_build_slurm_status_command_runner",
        lambda: runner,
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["status", run_uri, "--jobs", "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())

    assert stderr.getvalue() == ""
    assert payload["schema_version"] == "loom.cli.status.jobs.v1"
    assert payload["result"]["jobs"][0]["status"] == expected
    assert payload["result"]["jobs"][0]["scheduler_job_id"] == "100"
