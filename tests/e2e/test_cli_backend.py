"""End-to-end smoke tests for ``loom backend``."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from loom.cli.main import main
from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.stores import path_to_run_uri
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from tests.unit.loom.pipeline.execution.test_authority_adapter import (
    _pipeline,
    _store,
)


pytestmark = pytest.mark.e2e


def test_cli_backend_inspect_and_capabilities_smoke(tmp_path: Path) -> None:
    run_uri = _authority_run(tmp_path)

    inspect_stdout = io.StringIO()
    assert main(["backend", "inspect", run_uri], stdout=inspect_stdout) == 0
    assert inspect_stdout.getvalue().startswith(f"backend inspect {run_uri}: SUCCEEDED")

    capabilities_stdout = io.StringIO()
    assert (
        main(
            ["backend", "capabilities", run_uri, "--format", "json"],
            stdout=capabilities_stdout,
        )
        == 0
    )
    payload = json.loads(capabilities_stdout.getvalue())
    assert payload["ok"] is True
    assert payload["result"]["backend_name"] == "sqlite-per-run-authority"


def _authority_run(tmp_path: Path) -> str:
    authority = SQLitePerRunAuthorityStore(clock=lambda: "2020-01-01T00:00:00Z")
    run_store = _store(tmp_path, authority)
    run_uri = path_to_run_uri(tmp_path / "runs" / "run1")
    PipelineRunner(run_store=run_store).run(
        RunRequest(pipeline=_pipeline(), run_uri=run_uri)
    )
    return run_uri
