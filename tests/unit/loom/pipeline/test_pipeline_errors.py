"""Unit tests for pipeline-specific errors."""

import loom.pipeline.errors as errors


def test_pipeline_error_hierarchy() -> None:
    assert issubclass(errors.PipelineValidationError, errors.PipelineError)
    assert issubclass(errors.PipelineSpecError, errors.PipelineValidationError)
    assert issubclass(errors.InputBindingError, errors.PipelineValidationError)
    assert issubclass(errors.PipelineGraphError, errors.PipelineValidationError)
    assert issubclass(errors.PipelineCycleError, errors.PipelineGraphError)
    assert issubclass(errors.StageContractError, errors.PipelineError)
    assert issubclass(errors.StatusSerializationError, errors.PipelineValidationError)


def test_pipeline_error_exports() -> None:
    assert errors.__all__ == [
        "PipelineValidationError",
        "PipelineSpecError",
        "InputBindingError",
        "PipelineGraphError",
        "PipelineCycleError",
        "StageContractError",
        "StatusSerializationError",
    ]
