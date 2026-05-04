"""Package-level API tests for pipeline execution."""

import subprocess
import sys

import pytest


pytestmark = pytest.mark.package


def test_pipeline_execution_public_exports_are_phase_scoped() -> None:
    import loom
    import loom.pipeline
    import loom.pipeline.execution as execution

    assert execution.__all__ == [
        "ConfigSnapshotInputs",
        "ExecutionFailure",
        "FailurePolicy",
        "LifecycleError",
        "OutputValidationError",
        "PipelineExecutionError",
        "PipelineRunner",
        "PlanExecutionError",
        "RunRequest",
        "RunRequestError",
        "RunResult",
        "StageExecutionRequest",
        "StageExecutionResult",
        "StageExecutionRuntimeError",
        "StageRunResult",
        "next_stage_attempt",
        "run_pipeline",
        "validate_stage_outputs",
        "write_run_status",
        "write_stage_failed",
        "write_stage_running",
        "write_stage_skipped",
        "write_stage_succeeded",
    ]
    assert "PipelineRunner" not in loom.__all__
    assert {"PipelineRunner", "RunRequest", "RunResult"} <= set(loom.pipeline.__all__)


@pytest.mark.parametrize("forbidden", ["loom.cli", "subprocess"])
def test_pipeline_execution_import_does_not_import_forbidden_modules(
    forbidden: str,
) -> None:
    script = (
        "import sys\n"
        "import loom.pipeline.execution\n"
        f"if {forbidden!r} in sys.modules:\n"
        f"    raise SystemExit('{forbidden} was imported through loom.pipeline.execution')\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
