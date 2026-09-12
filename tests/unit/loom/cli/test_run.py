"""Ordinary run's finite managed contract and removal of execution bypasses."""

import io
import pytest
from loom.cli.main import main

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "flag", ["--executor", "--run-uri", "--resume", "--dry-run", "--authority-mode"]
)
def test_run_rejects_removed_bypass_controls(flag: str) -> None:
    output, errors = io.StringIO(), io.StringIO()
    code = main(
        ["run", "pipeline.yaml", "--deployment", "deployment.yaml", flag],
        stdout=output,
        stderr=errors,
    )
    assert code != 0
    assert "unrecognized" in errors.getvalue() or "argument" in errors.getvalue()


def test_run_requires_explicit_deployment() -> None:
    errors = io.StringIO()
    assert main(["run", "pipeline.yaml"], stdout=io.StringIO(), stderr=errors) != 0
    assert "--deployment" in errors.getvalue()
