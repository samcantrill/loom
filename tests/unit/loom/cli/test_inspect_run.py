from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from loom.cli.errors import CliError
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
    repository = object()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "loom.cli.inspect_run._read_only_queue_repository",
        lambda path: repository,
    )
    monkeypatch.setattr(
        "loom.diagnostics.run_inspection.inspect_run",
        lambda run_uri, **kwargs: (
            captured.update(kwargs)
            or RunInspectionFailure(RunInspectionFailureCode.NOT_FOUND)
        ),
    )
    assert inspect_run.build_inspect_run_result(
        "file:///tmp/run", queue_config=Path("queue.json")
    ) == RunInspectionFailure(RunInspectionFailureCode.NOT_FOUND)
    assert captured == {"queue_service": repository}


def test_selected_unix_source_never_falls_back_to_direct(
    monkeypatch, tmp_path: Path
) -> None:
    direct_calls: list[str] = []

    def direct(run_uri: str, **kwargs: object) -> RunInspectionFailure:
        direct_calls.append(run_uri)
        return RunInspectionFailure(RunInspectionFailureCode.NOT_FOUND)

    monkeypatch.setattr("loom.diagnostics.run_inspection.inspect_run", direct)

    with pytest.raises(CliError, match="run inspection failed"):
        inspect_run.build_inspect_run_result(
            "file:///tmp/run",
            endpoint=tmp_path / "missing.sock",
        )

    assert direct_calls == []


def test_selected_remote_source_never_falls_back_to_direct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    direct_calls: list[str] = []

    def direct(run_uri: str, **kwargs: object) -> RunInspectionFailure:
        del kwargs
        direct_calls.append(run_uri)
        return RunInspectionFailure(RunInspectionFailureCode.NOT_FOUND)

    class RemoteClient:
        def __init__(self, _config: object) -> None:
            pass

        def inspect_run(self, _run_uri: str) -> object:
            raise RuntimeError("remote is unavailable")

    monkeypatch.setattr("loom.diagnostics.run_inspection.inspect_run", direct)
    monkeypatch.setattr(
        "loom.queue.deployment.load_run_inspection_client_config",
        lambda _path: SimpleNamespace(client=object()),
    )
    monkeypatch.setattr(
        "loom.queue.agent_session_transport.RunInspectionHttpClient", RemoteClient
    )

    with pytest.raises(CliError, match="run inspection failed"):
        inspect_run.build_inspect_run_result(
            "file:///tmp/run", remote_config=Path("remote.yaml")
        )

    assert direct_calls == []
