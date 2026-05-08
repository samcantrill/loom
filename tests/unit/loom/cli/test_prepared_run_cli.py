"""Unit tests for ``loom prepared-run`` commands."""

from __future__ import annotations

import io
import json

from loom.cli.main import main


def test_prepared_run_continue_insufficient_state_json() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        [
            "prepared-run",
            "continue",
            "--run-uri",
            "file:///tmp/missing-run",
            "--executor",
            "slurm-single-job",
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
    assert payload["error"]["context"]["executor"] == "slurm-single-job"
    assert stderr.getvalue() == ""


def test_prepared_run_continue_requires_executor() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["prepared-run", "continue", "--run-uri", "file:///tmp/run"],
            stdout=stdout,
            stderr=stderr,
        )
        == 2
    )

    assert stdout.getvalue() == ""
    assert "--executor" in stderr.getvalue()
