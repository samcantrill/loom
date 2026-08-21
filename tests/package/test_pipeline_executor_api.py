"""Package-level API tests for pipeline executors."""

import pytest


pytestmark = pytest.mark.package


def test_pipeline_executor_public_exports_are_phase_scoped() -> None:
    import loom.pipeline.executors as executors

    assert executors.__all__ == [
        "ApptainerExecutor",
        "Executor",
        "ExecutorFactory",
        "ExecutorRegistration",
        "ExecutorRegistry",
        "create_default_executor_registry",
        "DockerExecutor",
        "ExecutorError",
        "LocalExecutor",
        "LocalExecutorError",
        "SingularityExecutor",
        "SubprocessExecutor",
        "SubprocessRunResult",
    ]
