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
        "ExecutionFailure",
        "LifecycleError",
        "OutputValidationError",
        "ParallelExecutionUnsupportedError",
        "PipelineExecutionError",
        "PlanExecutionError",
        "PREPARED_RUN_CONTINUATION_WHOLE_RUN",
        "PREPARED_RUN_SCHEMA_VERSION",
        "PreparedRunPayloadError",
        "PreparedRunRecord",
        "RunRequestError",
        "StageReportedFailure",
        "RuntimeServices",
        "ResourceAdmissionDecision",
        "ResourceAdmissionError",
        "ResourceAdmissionRequest",
        "ResourceAdmissionStatus",
        "ResourceLimitReconciliationResult",
        "ResourceLimitReconciliationStatus",
        "ResourceLeaseRequest",
        "StageExecutionRequest",
        "StageExecutionResult",
        "StageExecutionRuntimeError",
        "StageRunResult",
        "StageWorkerRequest",
        "StageWorkerResult",
        "StageWorkerStateError",
        "acquire_resource_admission",
        "create_authority_backed_serial_run_store",
        "prepare_stage_attempt",
        "reconcile_resource_limits",
        "redact_executor_metadata",
        "release_resource_admission",
        "resource_requests_from_runtime",
        "validate_stage_outputs",
    ]
    assert "PipelineRunner" not in loom.__all__
    assert not {"PipelineRunner", "RunRequest", "RunResult"} & set(
        loom.pipeline.__all__
    )


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
