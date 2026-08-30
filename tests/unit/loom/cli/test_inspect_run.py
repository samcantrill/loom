from __future__ import annotations

import io
from pathlib import Path

from loom.diagnostics import RunInspectionFailure, RunInspectionFailureCode
from loom.cli import inspect_run

from loom.cli.main import main


def test_inspect_run_requires_exactly_one_source() -> None:
    assert (
        main(
            ["inspect-run", "file:///tmp/run"],
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
        == 2
    )


def test_inspect_run_json_uses_fixed_envelope() -> None:
    stdout = io.StringIO()
    assert (
        main(
            ["inspect-run", "invalid", "--direct", "--format", "json"],
            stdout=stdout,
            stderr=io.StringIO(),
        )
        == 0
    )
    assert '"schema_version":"loom.cli.inspect_run.v1"' in stdout.getvalue()
    assert '"code":"invalid_request"' in stdout.getvalue()


def test_direct_queue_config_is_composed_into_the_projection(monkeypatch) -> None:
    service = object()
    captured: dict[str, object] = {}

    monkeypatch.setattr("loom.cli.sweep._started_queue_service", lambda path: service)
    monkeypatch.setattr(
        "loom.diagnostics.run_inspection.inspect_run",
        lambda run_uri, **kwargs: captured.update(kwargs)
        or RunInspectionFailure(RunInspectionFailureCode.NOT_FOUND),
    )
    assert inspect_run.build_inspect_run_result(
        "file:///tmp/run", queue_config=Path("queue.json")
    ) == RunInspectionFailure(RunInspectionFailureCode.NOT_FOUND)
    assert captured == {"queue_service": service}
