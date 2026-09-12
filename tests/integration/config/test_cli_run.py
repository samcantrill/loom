"""Ordinary CLI run uses the configured native deployment composition."""

import io
import json
from pathlib import Path

import pytest
from loom.cli.main import main
from tests.integration.queue.test_service_lifetime import _selection

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def test_cli_cold_run_and_identity_replay(tmp_path: Path) -> None:
    path = _selection(tmp_path)
    arguments = [
        "run",
        "pipeline.yaml",
        "--deployment",
        str(path),
        "--operation-id",
        "cli-run",
        "--format",
        "json",
    ]
    receipts = []
    for _ in range(2):
        output, errors = io.StringIO(), io.StringIO()
        assert main(arguments, stdout=output, stderr=errors) == 0, errors.getvalue()
        payload = json.loads(output.getvalue())
        assert payload["schema_version"] == "loom.cli.run.v3"
        assert payload["result"]["admission"]["state"] == "SUCCEEDED"
        assert payload["result"]["cleanup"]["coordinator"]["state"] == "stopped"
        receipts.append(payload["result"]["admission"]["admission_id"])
    assert receipts[0] == receipts[1]


@pytest.mark.parametrize(
    "config", ["/outside/pipeline.yaml", "../pipeline.yaml", "not-included.yaml"]
)
def test_cli_rejects_paths_outside_selected_project_before_start(
    tmp_path: Path, config: str
) -> None:
    path = _selection(tmp_path)
    output, errors = io.StringIO(), io.StringIO()
    assert (
        main(
            ["run", config, "--deployment", str(path), "--format", "json"],
            stdout=output,
            stderr=errors,
        )
        != 0
    )
    assert not (tmp_path / "binding.json").exists()
    assert not (tmp_path / "deployment").exists()
