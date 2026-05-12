"""Unit tests for ``loom prepared-run`` commands."""

from __future__ import annotations

import io
import json

import pytest

from loom.cli.main import main
from loom.pipeline.execution import InsufficientPreparedStateError


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


def test_prepared_run_continue_uses_authority_backed_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.pipeline.execution as execution

    calls: dict[str, object] = {}

    def create_store(*_args: object, **kwargs: object) -> object:
        calls["store_kwargs"] = kwargs
        return object()

    def continue_run(*, run_store: object, request: object) -> object:
        calls["run_store"] = run_store
        calls["request"] = request
        raise InsufficientPreparedStateError("file:///tmp/run")

    monkeypatch.setattr(
        execution,
        "create_authority_backed_serial_run_store",
        create_store,
    )
    monkeypatch.setattr(execution, "continue_prepared_run", continue_run)
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        [
            "prepared-run",
            "continue",
            "--run-uri",
            "file:///tmp/run",
            "--executor",
            "local",
            "--format",
            "json",
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 6
    request = calls["request"]
    assert getattr(request, "run_uri") == "file:///tmp/run"
    assert getattr(request, "executor") == "local"
    store_kwargs = calls["store_kwargs"]
    assert isinstance(store_kwargs, dict)
    assert store_kwargs["authority_config"] is not None
    assert store_kwargs["owner_id"] == "prepared-run"
    payload = json.loads(stdout.getvalue())
    assert (
        payload["error"]["code"]
        == "execution.prepared_run.insufficient_prepared_state"
    )
    assert payload["error"]["context"]["run_uri"] == "file:///tmp/run"
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
