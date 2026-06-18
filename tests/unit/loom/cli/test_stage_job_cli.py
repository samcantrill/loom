"""Unit tests for ``loom stage-job`` commands."""

from __future__ import annotations

import io
import json

import pytest

from loom.cli.main import main
from loom.pipeline.execution import StageJobRunResult
from loom.pipeline.status import RunStatus, StageStatus


def test_stage_job_run_passes_authority_fencing_to_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.pipeline.execution as execution

    calls: dict[str, object] = {}

    def create_store(*_args: object, **kwargs: object) -> object:
        calls["store_kwargs"] = kwargs
        return object()

    def run_job(
        *,
        run_store: object,
        request: object,
        **_kwargs: object,
    ) -> StageJobRunResult:
        calls["run_store"] = run_store
        calls["request"] = request
        return StageJobRunResult(
            schema_version=1,
            run_uri="file:///tmp/run",
            stage_name="build",
            attempt=2,
            status=StageStatus.SUCCEEDED,
            run_status=RunStatus.RUNNING,
        )

    monkeypatch.setattr(
        execution,
        "create_authority_backed_serial_run_store",
        create_store,
    )
    monkeypatch.setattr(execution, "run_stage_job", run_job)
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        [
            "stage-job",
            "run",
            "--run-uri",
            "file:///tmp/run",
            "--stage",
            "build",
            "--executor",
            "local",
            "--attempt",
            "2",
            "--authority-attempt-id",
            "attempt-1",
            "--authority-lease-id",
            "lease-1",
            "--authority-owner-id",
            "worker-1",
            "--authority-fencing-token",
            "fence-1",
            "--format",
            "json",
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    request = calls["request"]
    assert getattr(request, "authority_attempt_id") == "attempt-1"
    assert getattr(request, "authority_lease_id") == "lease-1"
    assert getattr(request, "authority_owner_id") == "worker-1"
    assert getattr(request, "authority_fencing_token") == "fence-1"
    store_kwargs = calls["store_kwargs"]
    assert isinstance(store_kwargs, dict)
    assert store_kwargs["authority_config"] is not None
    assert store_kwargs["owner_id"] == "stage-job"
    payload = json.loads(stdout.getvalue())
    assert payload["ok"] is True
    assert stderr.getvalue() == ""


def test_stage_job_run_rejects_recursive_executor_before_run_state() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        [
            "stage-job",
            "run",
            "--run-uri",
            "file:///tmp/missing-run",
            "--stage",
            "build",
            "--executor",
            "slurm-afterok",
            "--format",
            "json",
        ],
        stdout=stdout,
        stderr=stderr,
    )

    payload = json.loads(stdout.getvalue())
    assert code == 7
    assert payload["ok"] is False
    assert payload["error"]["code"] == "execution.continuation.unsupported_executor"
    assert payload["error"]["context"]["executor"] == "slurm-afterok"
    assert stderr.getvalue() == ""


def test_stage_job_run_invalid_attempt_is_usage_error() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "stage-job",
                "run",
                "--run-uri",
                "file:///tmp/run",
                "--stage",
                "build",
                "--executor",
                "local",
                "--attempt",
                "0",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 2
    )

    assert stdout.getvalue() == ""
    assert "attempt must be a positive integer" in stderr.getvalue()
