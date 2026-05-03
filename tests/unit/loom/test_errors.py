"""Unit tests for loom error hierarchy."""

import loom.errors as errors


def test_error_hierarchy_inherits_from_exception() -> None:
    assert issubclass(errors.LoomError, Exception)
    assert issubclass(errors.ValidationError, errors.LoomError)
    assert issubclass(errors.ContractError, errors.LoomError)
    assert issubclass(errors.ResourceError, errors.LoomError)
    assert issubclass(errors.ArtifactError, errors.LoomError)
    assert issubclass(errors.ConfigError, errors.LoomError)
    assert issubclass(errors.SerializationError, errors.LoomError)
    assert issubclass(errors.FingerprintError, errors.LoomError)
    assert issubclass(errors.PipelineError, errors.LoomError)
    assert issubclass(errors.ExecutionError, errors.LoomError)
    assert issubclass(errors.ProvenanceError, errors.LoomError)
    assert issubclass(errors.IOErrorBase, errors.LoomError)


def test_error_export_surface() -> None:
    assert errors.__all__ == [
        "LoomError",
        "ValidationError",
        "ContractError",
        "ResourceError",
        "ArtifactError",
        "ConfigError",
        "SerializationError",
        "FingerprintError",
        "PipelineError",
        "ExecutionError",
        "ProvenanceError",
        "IOErrorBase",
    ]


def test_error_module_does_not_export_ioerror_alias() -> None:
    assert not hasattr(errors, "IOError")
