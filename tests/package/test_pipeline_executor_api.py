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


def test_gpu_visibility_module_is_importable_without_a_root_reexport() -> None:
    from loom.pipeline.executors.gpu_visibility import (
        GpuVisibilityEvidence,
        project_apptainer_gpu_options,
        validate_cuda_visibility,
    )

    assert GpuVisibilityEvidence.__name__ == "GpuVisibilityEvidence"
    assert callable(project_apptainer_gpu_options)
    assert callable(validate_cuda_visibility)
