"""End-to-end submitted SLURM cancellation through the public CLI."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
import io
import json
from pathlib import Path
from typing import Any

import pytest

from loom.cli.main import main
from loom.pipeline.executors.slurm import FakeSlurmCommandRunner, SlurmCommandResult
from loom.pipeline.status import StageStatus, StageStatusRecord
from loom.pipeline.stores import (
    AuthorityBackendKind,
    AuthorityDeploymentProfile,
    authority_config_to_cli_args,
)
from loom.pipeline.stores.service_authority import LocalAuthorityService
from tests.support.slurm_status_fixtures import write_submitted_slurm_fixture

pytestmark = pytest.mark.e2e


@contextmanager
def _service_submitted_slurm_fixture(
    tmp_path: Path,
    stage_upstreams: Mapping[str, tuple[str, ...]],
    *,
    starting_job_id: int,
) -> Iterator[tuple[Any, str, tuple[str, ...], Path]]:
    with LocalAuthorityService.start() as service:
        authority_config = service.config(
            backend_kind=AuthorityBackendKind.MANAGED_SERVICE,
            deployment_profile=AuthorityDeploymentProfile.MANAGED_SERVICE,
        )
        store, run_uri, manifest_path = write_submitted_slurm_fixture(
            tmp_path,
            stage_upstreams,
            starting_job_id=starting_job_id,
            authority_config=authority_config,
        )
        yield (
            store,
            run_uri,
            authority_config_to_cli_args(authority_config),
            manifest_path,
        )


def test_cli_cancel_jobs_cancels_latest_active_slurm_submission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.cli.cancel as cancel_command

    with _service_submitted_slurm_fixture(
        tmp_path,
        {"extract": ()},
        starting_job_id=400,
    ) as (_store, run_uri, authority_args, _manifest_path):
        runner = FakeSlurmCommandRunner()
        monkeypatch.setattr(
            cancel_command,
            "_build_slurm_cancel_command_runner",
            lambda: runner,
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        assert (
            main(
                ["cancel", run_uri, "--jobs", *authority_args, "--format", "json"],
                stdout=stdout,
                stderr=stderr,
            )
            == 0
        )

        payload = json.loads(stdout.getvalue())

    assert stderr.getvalue() == ""
    assert payload["schema_version"] == "loom.cli.cancel.jobs.v1"
    assert payload["ok"] is True
    assert payload["result"]["status"] == "CANCELLED"
    assert payload["result"]["job_results"][0]["outcome"] == "cancelled"
    assert runner.calls == [("scancel", ("scancel", "400"))]


def test_cli_cancel_jobs_partial_failure_returns_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.cli.cancel as cancel_command

    with _service_submitted_slurm_fixture(
        tmp_path,
        {"extract": (), "train": ("extract",)},
        starting_job_id=500,
    ) as (_store, run_uri, authority_args, _manifest_path):
        runner = FakeSlurmCommandRunner(
            scripted_results={
                "scancel": (
                    SlurmCommandResult(
                        command="scancel",
                        argv=("scancel", "500"),
                        returncode=0,
                    ),
                    SlurmCommandResult(
                        command="scancel",
                        argv=("scancel", "501"),
                        returncode=1,
                        stderr="not found",
                    ),
                ),
            }
        )
        monkeypatch.setattr(
            cancel_command,
            "_build_slurm_cancel_command_runner",
            lambda: runner,
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        assert (
            main(
                ["cancel", run_uri, "--jobs", *authority_args, "--format", "json"],
                stdout=stdout,
                stderr=stderr,
            )
            == 5
        )

        payload = json.loads(stdout.getvalue())

    assert stderr.getvalue() == ""
    assert payload["ok"] is False
    assert payload["result"]["status"] == "PARTIAL"
    assert payload["result"]["failed_count"] == 1


def test_cli_cancel_jobs_missing_scancel_returns_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.cli.cancel as cancel_command

    with _service_submitted_slurm_fixture(
        tmp_path,
        {"extract": ()},
        starting_job_id=600,
    ) as (_store, run_uri, authority_args, _manifest_path):
        runner = FakeSlurmCommandRunner(unavailable_commands=("scancel",))
        monkeypatch.setattr(
            cancel_command,
            "_build_slurm_cancel_command_runner",
            lambda: runner,
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        assert (
            main(
                ["cancel", run_uri, "--jobs", *authority_args, "--format", "json"],
                stdout=stdout,
                stderr=stderr,
            )
            == 5
        )

        payload = json.loads(stdout.getvalue())

    assert stderr.getvalue() == ""
    assert payload["ok"] is False
    assert payload["result"]["status"] == "UNKNOWN"
    assert payload["result"]["job_results"][0]["command_record"]["returncode"] == 127


def test_cli_cancel_jobs_skips_terminal_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.cli.cancel as cancel_command

    with _service_submitted_slurm_fixture(
        tmp_path,
        {"extract": ()},
        starting_job_id=700,
    ) as (store, run_uri, authority_args, _manifest_path):
        store.write_stage_status(
            run_uri,
            "extract",
            StageStatusRecord(
                run_uri=run_uri,
                stage_name="extract",
                status=StageStatus.SUCCEEDED,
                attempt=1,
                updated_at="2026-05-08T00:00:09Z",
            ),
        )
        runner = FakeSlurmCommandRunner()
        monkeypatch.setattr(
            cancel_command,
            "_build_slurm_cancel_command_runner",
            lambda: runner,
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        assert (
            main(
                ["cancel", run_uri, "--jobs", *authority_args, "--format", "json"],
                stdout=stdout,
                stderr=stderr,
            )
            == 0
        )

        payload = json.loads(stdout.getvalue())

    assert payload["result"]["status"] == "COMPLETED"
    assert payload["result"]["job_results"][0]["outcome"] == "skipped_terminal"
    assert runner.calls == []
    assert stderr.getvalue() == ""
