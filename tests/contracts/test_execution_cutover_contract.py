"""Hard execution cutover leaves only the native run owner and worker primitives."""

import importlib.util
import io

import pytest

from loom.cli.main import main

pytestmark = pytest.mark.contract


@pytest.mark.parametrize(
    "module",
    [
        "loom.pipeline.execution.runner",
        "loom.pipeline.execution.continuation",
        "loom.pipeline.execution.offline_adapter",
        "loom.queue.service",
        "loom.queue.client",
        "loom.queue.controller",
        "loom.queue.local",
        "loom.queue.slurm",
        "loom.cli.prepared_run",
        "loom.cli.stage_job",
        "loom.cli.stage",
        "loom.pipeline.executors.slurm.submission",
    ],
)
def test_retired_engine_modules_are_unavailable(module):
    assert importlib.util.find_spec(module) is None


@pytest.mark.parametrize(
    "argv",
    [
        ["stage", "run"],
        ["stage-job", "run"],
        ["prepared-run", "continue"],
        ["queue", "start"],
        ["queue", "drain-foreground"],
        ["queue", "drive-slurm"],
    ],
)
def test_retired_execution_commands_fail_at_argument_boundary(argv):
    stderr = io.StringIO()
    assert main(argv, stdout=io.StringIO(), stderr=stderr) == 2
    assert "invalid choice" in stderr.getvalue()
