"""End-to-end smoke tests for ``loom backend``."""

from __future__ import annotations

from collections.abc import Iterator
import io
import json
from pathlib import Path

import pytest

from loom.cli.main import main
from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.stores import (
    AuthorityConfig,
    authority_config_to_cli_args,
    path_to_run_uri,
)
from loom.pipeline.stores.service_authority import LocalAuthorityService
from tests.unit.loom.pipeline.execution.test_authority_adapter import _pipeline


pytestmark = pytest.mark.e2e


@pytest.fixture
def authority_context() -> Iterator[tuple[AuthorityConfig, tuple[str, ...]]]:
    with LocalAuthorityService.start() as service:
        config = service.config()
        yield config, authority_config_to_cli_args(config)


def test_cli_backend_inspect_and_capabilities_smoke(
    tmp_path: Path,
    authority_context: tuple[AuthorityConfig, tuple[str, ...]],
) -> None:
    authority_config, authority_args = authority_context
    run_uri = _authority_run(tmp_path, authority_config=authority_config)

    inspect_stdout = io.StringIO()
    assert (
        main(["backend", "inspect", run_uri, *authority_args], stdout=inspect_stdout)
        == 0
    )
    assert inspect_stdout.getvalue().startswith(f"backend inspect {run_uri}: SUCCEEDED")

    capabilities_stdout = io.StringIO()
    assert (
        main(
            ["backend", "capabilities", run_uri, *authority_args, "--format", "json"],
            stdout=capabilities_stdout,
        )
        == 0
    )
    payload = json.loads(capabilities_stdout.getvalue())
    assert payload["ok"] is True
    assert payload["result"]["backend_name"] == "local-authority-service"


def _authority_run(tmp_path: Path, *, authority_config: AuthorityConfig) -> str:
    run_store = create_authority_backed_serial_run_store(
        tmp_path / "runs",
        authority_config=authority_config,
    )
    run_uri = path_to_run_uri(tmp_path / "runs" / "run1")
    PipelineRunner(run_store=run_store).run(
        RunRequest(pipeline=_pipeline(), run_uri=run_uri)
    )
    return run_uri
