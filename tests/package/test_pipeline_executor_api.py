"""Package-level API tests for pipeline executors."""

import pytest


pytestmark = pytest.mark.package


def test_pipeline_executor_public_exports_are_phase_scoped() -> None:
    import loom.pipeline.executors as executors

    assert executors.__all__ == [
        "Executor",
        "ExecutorError",
        "LocalExecutor",
        "LocalExecutorError",
    ]
