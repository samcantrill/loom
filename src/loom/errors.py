"""Error hierarchy for loom."""


class LoomError(Exception):
    """Base exception for loom."""


class ValidationError(LoomError):
    """Error raised for invalid validation state."""


class ContractError(LoomError):
    """Error raised for protocol or contract violations."""


class ArtifactError(LoomError):
    """Error raised for artifact-level failures."""


class ConfigError(LoomError):
    """Error raised for config-related operations."""


class PipelineError(LoomError):
    """Error raised for pipeline-level failures."""


class ExecutionError(LoomError):
    """Error raised for execution-level failures."""


class IOErrorBase(LoomError):
    """Base error for Loom I/O operations."""


__all__ = [
    "LoomError",
    "ValidationError",
    "ContractError",
    "ArtifactError",
    "ConfigError",
    "PipelineError",
    "ExecutionError",
    "IOErrorBase",
]
